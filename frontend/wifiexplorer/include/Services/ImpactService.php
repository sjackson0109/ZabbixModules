<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\VlanService;

/**
 * Blast radius of a wired failure (requirements section 15): if this switch, or this port, fails, which APs,
 * SSIDs, VLANs, floors and clients are affected?
 *
 * The answer reverses the Phase C uplinks and Phase D upstream walks; nothing is guessed from names or geometry.
 *
 *   lost             the element is the AP's own port or switch, or on its path with no alternative seen;
 *   degraded         a LAG on the path loses a member but keeps others up;
 *   reroute_possible a switch below the failure has an STP alternate or backup port that is up, so spanning tree may
 *                    reconverge (whether it carries each VLAN is shown, not assumed);
 *   cannot_assess    the AP's uplink or path is unknown or stops before the element could be ruled out.
 *
 * Client counts are the clients associated now (observed); how many roam to a neighbouring AP is not predicted,
 * so the total is labelled an estimate. PoE is not collected, so whether an AP also loses power is not stated.
 */
final class ImpactService {
    private array $hosts = [];
    private array $interfaces = [];
    private array $aggregators = [];

    public function __construct(array $network) {
        $this->hosts = WiredIndex::hosts($network);
        $this->interfaces = WiredIndex::interfaces($network);
        $this->aggregators = WiredIndex::aggregators($network);
    }

    /**
     * @param array $aps   ap_uid => AP with uplink, chain, ssids, placement and clients
     * @param array $ssids SsidService rows
     */
    public function build(string $failHost, string $failInterface, array $aps, array $ssids): array {
        $host = $this->hosts[$failHost] ?? null;
        if ($host === null) {
            return ['status'=>'not_visible', 'target'=>null];
        }
        $interface = null;
        if ($failInterface !== '') {
            $interface = $this->interfaces[$failHost][$failInterface] ?? null;
            if ($interface === null) {
                return ['status'=>'interface_not_visible', 'target'=>['hostid'=>$failHost, 'name'=>$host['name']]];
            }
        }
        $aggregator = $failInterface !== '' ? ($this->aggregators[$failHost][$failInterface] ?? null) : null;
        $target = ['hostid'=>$failHost, 'name'=>$host['name'], 'interface_uid'=>$failInterface ?: null,
            'interface_name'=>$interface['name'] ?? null, 'lag_member_of'=>$aggregator !== null
                ? ($this->interfaces[$failHost][$aggregator]['name'] ?? $aggregator) : null,
            'is_root'=>(bool) array_filter($host['stp'] ?? [], static fn($b) => ($b['instance'] ?? null) === 0
                && ($b['is_root'] ?? false))];

        $affected = [];
        $unaffected = 0;
        foreach ($aps as $apUid => $ap) {
            $impact = $this->apImpact($ap, $failHost, $failInterface, $aggregator);
            if ($impact === null) {
                ++$unaffected;
                continue;
            }
            $affected[$apUid] = ['ap_uid'=>$apUid, 'clients'=>$ap['clients'], 'floor_id'=>$ap['placement']['floor_id'] ?? null,
                'ssids'=>array_keys(array_filter($ap['ssids'], static fn($s) => $s['status'] === 'broadcasting'))] + $impact;
        }

        // SSIDs, VLANs and floors from the APs that lose service; reroutes and unknowns are listed separately.
        $lost = array_filter($affected, static fn($a) => $a['impact'] === 'lost');
        $ssidRows = [];
        foreach ($ssids as $ssid) {
            $broadcasting = array_filter($ssid['expected'], static fn($e) => $e['status'] === 'broadcasting');
            if (!$broadcasting) {
                continue;
            }
            $losing = array_filter($broadcasting, static fn($e) => isset($lost[$e['ap_uid']]));
            $risk = array_filter($broadcasting, static fn($e) => isset($affected[$e['ap_uid']]) && !isset($lost[$e['ap_uid']]));
            if (!$losing && !$risk) {
                continue;
            }
            $ssidRows[] = ['ssid_uid'=>$ssid['ssid_uid'], 'name'=>$ssid['name'], 'broadcasting'=>count($broadcasting),
                'lost'=>count($losing), 'at_risk'=>count($risk), 'all_lost'=>count($losing) === count($broadcasting),
                'vlans'=>array_values(array_unique(array_filter(array_column($losing, 'vlan'))))];
        }
        $vlans = [];
        foreach ($lost as $row) {
            foreach ($aps[$row['ap_uid']]['ssids'] as $state) {
                if ($state['vlan'] !== null && $state['status'] === 'broadcasting') {
                    $vlans[$state['vlan']] = true;
                }
            }
        }
        ksort($vlans);
        $floors = [];
        foreach ($lost as $row) {
            if ($row['floor_id'] !== null) {
                $floors[$row['floor_id']] = ($floors[$row['floor_id']] ?? 0) + 1;
            }
        }
        $known = array_filter($lost, static fn($a) => $a['clients'] !== null);
        $counts = array_fill_keys(['lost', 'degraded', 'reroute_possible', 'cannot_assess'], 0);
        foreach ($affected as $row) {
            ++$counts[$row['impact']];
        }
        return ['status'=>'ok', 'target'=>$target, 'aps'=>array_values($affected), 'counts'=>$counts,
            'unaffected'=>$unaffected, 'ssids'=>$ssidRows, 'vlans'=>array_keys($vlans), 'floors'=>$floors,
            'clients'=>['estimated'=>array_sum(array_column($known, 'clients')),
                'aps_without_count'=>count($lost) - count($known), 'kind'=>'estimated']];
    }

    /** @return array{impact: string, reason: string, at_hop: ?int, alternates: array}|null null when unaffected */
    private function apImpact(array $ap, string $failHost, string $failInterface, ?string $aggregator): ?array {
        $uplink = $ap['uplink'];
        $chain = $ap['chain'];
        $result = static fn(string $impact, string $reason, ?int $hop = null, array $alternates = []) =>
            ['impact'=>$impact, 'reason'=>$reason, 'at_hop'=>$hop, 'alternates'=>$alternates];
        if ($uplink === null || $uplink['hostid'] === null || $chain === null || $chain['ports'] === []) {
            return $result('cannot_assess', 'uplink_unknown');
        }
        foreach ($chain['ports'] as $index => $port) {
            if ($port['hostid'] !== $failHost) {
                continue;
            }
            if ($failInterface === '') {
                if ($index === 0) {
                    return $result('lost', 'ap_switch', 0);
                }
                // The whole switch: the AP's switch below it may still reach a new root another way.
                return $this->reroute($chain, $index, 'upstream_switch');
            }
            $hit = $port['interface_uid'] === $failInterface;
            $member = $aggregator !== null && $port['interface_uid'] === $aggregator;
            if (!$hit && !$member) {
                continue;
            }
            if ($index === 0) {
                return $result('lost', 'ap_port', 0);
            }
            if ($member) {
                $others = array_filter($port['lag_members'], fn($uid) => $uid !== $failInterface
                    && ($this->interfaces[$failHost][$uid]['oper_status'] ?? null) === 'up');
                if ($others) {
                    return $result('degraded', 'lag_member', $index);
                }
            }
            return $this->reroute($chain, $index, 'upstream_port');
        }
        if ($chain['status'] !== 'complete') {
            return $result('cannot_assess', 'path_'.$chain['status']);
        }
        return null;
    }

    /** A failure at hop $index: look for STP alternates on the switches between the AP and the failure. */
    private function reroute(array $chain, int $index, string $reason): array {
        $alternates = [];
        $below = array_unique(array_column(array_slice($chain['ports'], 0, $index), 'hostid'));
        $failedHost = $chain['ports'][$index]['hostid'];
        foreach ($below as $hostid) {
            if ($hostid === $failedHost && $reason === 'upstream_switch') {
                continue;
            }
            foreach ($this->interfaces[$hostid] ?? [] as $uid => $interface) {
                foreach ($interface['stp'] ?? [] as $row) {
                    if (($row['instance'] ?? null) === 0 && in_array($row['role'] ?? null, ['alternate', 'backup'], true)
                            && ($interface['oper_status'] ?? null) === 'up') {
                        $alternates[] = ['hostid'=>$hostid, 'interface_uid'=>$uid, 'switch_name'=>$this->hosts[$hostid]['name'],
                            'interface_name'=>$interface['name'] ?? $uid,
                            'carried'=>$interface['vlan']['carried'] ?? null];
                    }
                }
            }
        }
        return ['impact'=>$alternates ? 'reroute_possible' : 'lost', 'reason'=>$reason, 'at_hop'=>$index,
            'alternates'=>$alternates];
    }

    /** Whether an alternate port carries a VLAN, for the view. */
    public static function carries(?string $carried, int $vlan): ?bool {
        return $carried === null ? null : in_array($vlan, VlanService::expand($carried), true);
    }
}
