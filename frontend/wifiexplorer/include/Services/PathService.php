<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\VlanService;

/**
 * VLAN service-path assurance (requirements section 12): for each SSID with a declared VLAN, AP by AP, does the
 * VLAN reach the AP's switch port and continue hop by hop to the spanning-tree root?
 *
 * The path is never inferred from geometry or names. It follows Network Explorer's own model:
 *
 *   1. the AP's uplink port (Phase C);
 *   2. on each switch, its instance-0 (CST/CIST) root port, and the LLDP link (or LAG) from that port to the
 *      upstream switch's designated port;
 *   3. until a switch reports itself as the root bridge.
 *
 * Every port on the way is checked from current observations: link up, the VLAN in the port's current egress
 * membership, and not blocking. The result names the first failing hop. Anything not proven is "unknown" (stale or
 * missing data) or "partial" (the walk stopped before the root), never complete. Layer 3 (the VLAN's gateway) is
 * not checked.
 *
 * Limitations kept visible: with MSTP the walk follows the CIST, which may not be the VLAN's instance; bridges
 * that disagree on the root make the path unproven.
 */
final class PathService {
    public const MAX_HOPS = 16;
    private const BLOCKING = ['blocking', 'discarding', 'broken', 'disabled'];

    private array $hosts = [];
    private array $interfaces = [];
    private array $links = [];
    private array $aggregators = [];
    private array $quality = [];

    /** @param array $network Network Explorer's buildScope() model of the site */
    public function __construct(array $network) {
        $this->hosts = WiredIndex::hosts($network);
        $this->interfaces = WiredIndex::interfaces($network);
        $this->aggregators = WiredIndex::aggregators($network);
        foreach ($network['quality'] as $row) {
            $this->quality[$row['hostid']][$row['dataset']] = $row;
        }
        $edges = [];
        foreach ($network['edges'] as $edge) {
            $edges[$edge['id']] = $edge;
            if ($edge['source'] === null || $edge['target'] === null || $edge['source_uid'] === null
                    || $edge['target_uid'] === null || $edge['source'] === $edge['target']) {
                continue;
            }
            $this->links[$edge['source']][$edge['source_uid']][] = [$edge['target'], $edge['target_uid'], $edge['id']];
            $this->links[$edge['target']][$edge['target_uid']][] = [$edge['source'], $edge['source_uid'], $edge['id']];
        }
        foreach ($network['lags'] as $lag) {
            if ($lag['interface_uid'] === null) {
                continue;
            }
            // A LAG's link is the union of its members' links, seen from the aggregator.
            foreach ($lag['members'] as $member) {
                foreach ($this->links[$lag['hostid']][$member['uid']] ?? [] as $link) {
                    $this->links[$lag['hostid']][$lag['interface_uid']][] = $link;
                }
            }
        }
    }

    /**
     * @param array $aps   ap_uid => AP with its uplink
     * @param array $ssids SsidService rows (expected APs with declared VLANs)
     */
    public function build(array $aps, array $ssids): array {
        $chains = [];
        foreach ($aps as $apUid => $ap) {
            $chains[$apUid] = $this->chain($ap['uplink'] ?? null);
        }
        $paths = [];
        $findings = [];
        foreach ($ssids as $ssid) {
            $results = [];
            foreach ($ssid['expected'] as $expected) {
                if ($expected['vlan'] === null || !isset($chains[$expected['ap_uid']])) {
                    continue;
                }
                $results[$expected['ap_uid']] = $this->evaluate($chains[$expected['ap_uid']], $expected['vlan'])
                    + ['ap_uid'=>$expected['ap_uid'], 'vlan'=>$expected['vlan']];
            }
            if (!$results) {
                continue;
            }
            $counts = array_fill_keys(['complete', 'failed', 'partial', 'unknown'], 0);
            foreach ($results as $result) {
                ++$counts[$result['status']];
            }
            $paths[$ssid['ssid_uid']] = ['ssid_uid'=>$ssid['ssid_uid'], 'name'=>$ssid['name'], 'results'=>$results,
                'counts'=>$counts];
            $findings = array_merge($findings, $this->findings($ssid, $results, $aps));
        }
        return ['chains'=>$chains, 'paths'=>$paths, 'findings'=>$findings];
    }

    /**
     * The VLAN-independent upstream walk from an AP's uplink port to the root bridge.
     * @return array{status: string, reason: ?string, ports: array, root_hostid: ?string, caveats: string[]}
     */
    public function chain(?array $uplink): array {
        $chain = ['status'=>'unknown', 'reason'=>null, 'ports'=>[], 'root_hostid'=>null, 'caveats'=>[]];
        if ($uplink === null || $uplink['hostid'] === null || $uplink['interface_uid'] === null
                || !in_array($uplink['state'], ['confirmed', 'switch_only', 'ap_only'], true)) {
            return ['reason'=>'uplink_'.($uplink['state'] ?? 'unresolved')] + $chain;
        }
        $host = $uplink['hostid'];
        $chain['ports'][] = $this->port($host, $uplink['interface_uid'], 'access', null);
        $visited = [];
        $roots = [];
        for ($hop = 0; $hop < self::MAX_HOPS; ++$hop) {
            if (isset($visited[$host])) {
                return ['status'=>'partial', 'reason'=>'loop'] + $chain;
            }
            $visited[$host] = true;
            $bridge = null;
            foreach ($this->hosts[$host]['stp'] ?? [] as $row) {
                if (($row['instance'] ?? null) === 0) {
                    $bridge = $row;
                }
            }
            $stp = $this->quality[$host]['stp'] ?? null;
            if ($bridge === null) {
                return ['status'=>'partial', 'reason'=>$stp === null ? 'stp_not_collected' : 'stp_no_bridge',
                    'stop_hostid'=>$host] + $chain;
            }
            if (($stp['freshness'] ?? 'unknown') !== 'current') {
                return ['status'=>'partial', 'reason'=>'stp_stale', 'stop_hostid'=>$host] + $chain;
            }
            if (($bridge['protocol'] ?? null) === 'mstp' && !in_array('mstp_cist_only', $chain['caveats'], true)) {
                $chain['caveats'][] = 'mstp_cist_only';
            }
            if (isset($bridge['root_bridge_id'])) {
                $roots[$bridge['root_bridge_id']] = true;
            }
            if (count($roots) > 1) {
                return ['status'=>'partial', 'reason'=>'stp_root_disagreement', 'stop_hostid'=>$host] + $chain;
            }
            if ($bridge['is_root'] ?? false) {
                return ['status'=>'complete', 'root_hostid'=>$host] + $chain;
            }
            $rootPort = $bridge['root_port_uid'] ?? null;
            if (!is_string($rootPort)) {
                return ['status'=>'partial', 'reason'=>'no_root_port', 'stop_hostid'=>$host] + $chain;
            }
            $rootPort = $this->aggregators[$host][$rootPort] ?? $rootPort;
            $peers = [];
            foreach ($this->links[$host][$rootPort] ?? [] as [$peerHost, $peerUid, $edgeId]) {
                $peerUid = $this->aggregators[$peerHost][$peerUid] ?? $peerUid;
                $peers[$peerHost.'/'.$peerUid] = [$peerHost, $peerUid, $edgeId];
            }
            $chain['ports'][] = $this->port($host, $rootPort, 'root_port', null);
            if (count($peers) !== 1) {
                return ['status'=>'partial', 'reason'=>$peers ? 'upstream_link_ambiguous' : 'upstream_link_unresolved',
                    'stop_hostid'=>$host] + $chain;
            }
            [$peerHost, $peerUid, $edgeId] = reset($peers);
            if (!isset($this->hosts[$peerHost])) {
                return ['status'=>'partial', 'reason'=>'upstream_not_visible', 'stop_hostid'=>$host] + $chain;
            }
            $chain['ports'][] = $this->port($peerHost, $peerUid, 'designated', $edgeId);
            $host = $peerHost;
        }
        return ['status'=>'partial', 'reason'=>'too_many_hops'] + $chain;
    }

    private function port(string $hostid, string $uid, string $role, ?string $edgeId): array {
        $interface = $this->interfaces[$hostid][$uid] ?? null;
        return ['hostid'=>$hostid, 'interface_uid'=>$uid, 'role'=>$role, 'edge_id'=>$edgeId,
            'switch_name'=>$this->hosts[$hostid]['name'] ?? null, 'interface_name'=>$interface['name'] ?? null,
            'explorer_url'=>$interface['explorer_url'] ?? null,
            'lag_members'=>$interface !== null ? $this->members($hostid, $uid) : []];
    }

    private function members(string $hostid, string $uid): array {
        $members = [];
        foreach ($this->aggregators[$hostid] ?? [] as $member => $aggregator) {
            if ($aggregator === $uid) {
                $members[] = $member;
            }
        }
        return $members;
    }

    /**
     * One VLAN along one chain. Every hop is checked so the first failure is named even after an unknown one.
     * @return array{status: string, reason: ?string, failed_hop: ?int, hops: array, caveats: string[]}
     */
    public function evaluate(array $chain, int $vlan): array {
        $hops = [];
        $failed = null;
        $unknown = null;
        foreach ($chain['ports'] as $index => $port) {
            [$status, $reason, $tagging] = $this->check($port, $vlan);
            $hops[] = $port + ['status'=>$status, 'reason'=>$reason, 'tagging'=>$tagging];
            if ($status === 'failed' && $failed === null) {
                $failed = $index;
            }
            if ($status === 'unknown' && $unknown === null) {
                $unknown = $index;
            }
        }
        $caveats = $chain['caveats'];
        if ($failed !== null) {
            return ['status'=>'failed', 'reason'=>$hops[$failed]['reason'], 'failed_hop'=>$failed, 'hops'=>$hops,
                'uncertain_before'=>$unknown !== null && $unknown < $failed, 'caveats'=>$caveats,
                'chain_status'=>$chain['status']];
        }
        if ($unknown !== null) {
            return ['status'=>'unknown', 'reason'=>$hops[$unknown]['reason'], 'failed_hop'=>$unknown, 'hops'=>$hops,
                'uncertain_before'=>false, 'caveats'=>$caveats, 'chain_status'=>$chain['status']];
        }
        if ($chain['status'] !== 'complete') {
            return ['status'=>$chain['status'], 'reason'=>$chain['reason'], 'failed_hop'=>null, 'hops'=>$hops,
                'uncertain_before'=>false, 'caveats'=>$caveats, 'chain_status'=>$chain['status']];
        }
        if (in_array('mstp_cist_only', $caveats, true) && $this->mappedElsewhere($chain, $vlan)) {
            return ['status'=>'partial', 'reason'=>'mstp_instance', 'failed_hop'=>null, 'hops'=>$hops,
                'uncertain_before'=>false, 'caveats'=>$caveats, 'chain_status'=>$chain['status']];
        }
        return ['status'=>'complete', 'reason'=>null, 'failed_hop'=>null, 'hops'=>$hops, 'uncertain_before'=>false,
            'caveats'=>$caveats, 'chain_status'=>$chain['status']];
    }

    /** @return array{0: string, 1: ?string, 2: ?string} status (ok, failed, unknown), reason, tagging */
    private function check(array $port, int $vlan): array {
        $interface = $this->interfaces[$port['hostid']][$port['interface_uid']] ?? null;
        if ($interface === null) {
            return ['unknown', 'interface_not_visible', null];
        }
        if (($interface['quality']['freshness'] ?? 'unknown') !== 'current') {
            return ['unknown', 'port_state_stale', null];
        }
        if (($interface['oper_status'] ?? null) !== 'up') {
            return in_array($interface['oper_status'] ?? null, ['down', 'lowerLayerDown', 'notPresent'], true)
                ? ['failed', 'port_down', null] : ['unknown', 'port_state_unknown', null];
        }
        $membership = $interface['vlan'] ?? null;
        if ($membership === null) {
            $collected = $this->quality[$port['hostid']]['vlan'] ?? null;
            return ['unknown', $collected === null ? 'vlan_not_collected' : 'vlan_membership_unknown', null];
        }
        if (($this->quality[$port['hostid']]['vlan']['freshness'] ?? 'unknown') !== 'current') {
            return ['unknown', 'vlan_data_stale', null];
        }
        if (!in_array($vlan, VlanService::expand($membership['carried'] ?? ''), true)) {
            return ['failed', $port['role'] === 'access' ? 'vlan_not_on_ap_port' : 'vlan_not_carried', null];
        }
        $tagging = in_array($vlan, VlanService::expand($membership['untagged'] ?? ''), true) ? 'untagged' : 'tagged';
        foreach ($interface['stp'] ?? [] as $row) {
            if (($row['instance'] ?? null) === 0 && in_array($row['state'] ?? null, self::BLOCKING, true)) {
                return ['failed', 'stp_blocking', $tagging];
            }
        }
        return ['ok', null, $tagging];
    }

    /** Whether any bridge on the chain maps this VLAN to an MSTP instance other than the CIST. */
    private function mappedElsewhere(array $chain, int $vlan): bool {
        foreach (array_unique(array_column($chain['ports'], 'hostid')) as $hostid) {
            foreach ($this->hosts[$hostid]['stp'] ?? [] as $row) {
                if (($row['instance'] ?? 0) !== 0 && in_array($vlan, VlanService::expand((string) ($row['vlans'] ?? '')), true)) {
                    return true;
                }
            }
        }
        return false;
    }

    /** One warning per SSID and failing hop (several APs often fail at the same trunk), one note per unproven SSID. */
    private function findings(array $ssid, array $results, array $aps): array {
        $findings = [];
        $groups = [];
        $unproven = [];
        foreach ($results as $apUid => $result) {
            if ($result['status'] === 'failed') {
                $hop = $result['hops'][$result['failed_hop']];
                // Access ports fail one per AP; they are one finding per SSID and reason, trunks one per port.
                $groups[($hop['role'] === 'access' ? 'access' : $hop['hostid'].'/'.$hop['interface_uid']).'/'
                    .$result['reason'].'/'.$result['vlan']][] = $apUid;
            }
            elseif ($result['status'] !== 'complete') {
                $unproven[] = $apUid;
            }
        }
        $reasons = ['port_down'=>_('the port is down'), 'vlan_not_on_ap_port'=>_('the AP\'s switch port does not carry it'),
            'vlan_not_carried'=>_('the port does not carry it'), 'stp_blocking'=>_('spanning tree blocks the port')];
        foreach ($groups as $apUids) {
            $result = $results[$apUids[0]];
            $hop = $result['hops'][$result['failed_hop']];
            $names = array_map(static fn($uid) => $aps[$uid]['name'] ?? $uid, $apUids);
            $hops = array_map(static fn($uid) => $results[$uid]['hops'][$results[$uid]['failed_hop']], $apUids);
            $title = $hop['role'] === 'access' && count($apUids) > 1
                ? _s('VLAN %1$s (%2$s) is not on the switch ports of %3$s APs', $result['vlan'], $ssid['name'], count($apUids))
                : _s('VLAN %1$s (%2$s) stops at %3$s %4$s for %5$s AP(s)', $result['vlan'], $ssid['name'],
                    $hop['switch_name'] ?? '?', $hop['interface_name'] ?? '?', count($apUids));
            $findings[] = WifiFinding::create('wifi_path_failed', 'warning', $hop['hostid'], 'ssid', $ssid['ssid_uid'],
                $title,
                _s('Hop %1$s of the path from %2$s towards the spanning-tree root: %3$s.', $result['failed_hop'] + 1,
                    implode(', ', array_slice($names, 0, 5)).(count($names) > 5 ? ', …' : ''),
                    $reasons[$result['reason']] ?? $result['reason']),
                array_map(static fn($h) => ['dataset'=>$result['reason'] === 'port_down' ? 'interfaces'
                    : ($result['reason'] === 'stp_blocking' ? 'stp' : 'vlan'), 'hostid'=>$h['hostid'], 'observed_at'=>null,
                    'fact'=>($h['switch_name'] ?? '?').' '.($h['interface_name'] ?? $h['interface_uid']).': '.$result['reason']],
                    array_slice($hops, 0, 10)),
                'current',
                $result['reason'] === 'port_down' ? _('Restore the link.')
                    : _s('Add VLAN %1$s to the port\'s allowed VLANs, or correct the declared VLAN.', $result['vlan']));
        }
        if ($unproven) {
            $first = $results[$unproven[0]];
            $findings[] = WifiFinding::create('wifi_path_unproven', 'info', $aps[$unproven[0]]['owner_hostid'], 'ssid',
                $ssid['ssid_uid'],
                _s('%1$s: the VLAN path of %2$s AP(s) is not proven', $ssid['name'], count($unproven)),
                _('Uplink, VLAN or spanning-tree data is missing or stale on the way, so neither success nor failure can be shown.'),
                array_map(static fn($uid) => ['dataset'=>'wired', 'hostid'=>null, 'observed_at'=>null,
                    'fact'=>($aps[$uid]['name'] ?? $uid).': '.($results[$uid]['reason'] ?? $results[$uid]['status'])],
                    array_slice($unproven, 0, 10)),
                'unknown', $first['reason'] !== null && strpos((string) $first['reason'], 'uplink_') === 0
                    ? _('Resolve the AP uplinks first (LLDP on the switches).') : _('Check VLAN and STP collection on the switches in Network Explorer.'),
                'inferred');
        }
        return $findings;
    }
}
