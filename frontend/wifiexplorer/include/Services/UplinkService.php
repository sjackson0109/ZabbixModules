<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\DataGateway;
use Modules\NetworkExplorer\Services\DatasetReader;
use Modules\NetworkExplorer\Services\IdentityResolver;
use Modules\NetworkExplorer\Services\NetworkScope;
use Modules\NetworkExplorer\Services\NetworkService;

/**
 * Wired uplinks: which switch interface each AP is cabled to (requirements section 10), from Network Explorer's own
 * model and datasets, read as the viewing user. Nothing about switches, VLANs or STP is interpreted here; this only
 * matches APs to the switch ports Network Explorer already describes.
 *
 * Switch side: a switch's LLDP neighbour on a port whose chassis ID is the AP's MAC address (strong), or whose
 * management address is the AP's address. A system name alone never identifies an AP.
 * AP side: an AP host that also carries Network Explorer's LLDP producer, resolved to a switch interface with
 * Network Explorer's IdentityResolver (same domain rules, same interface identity).
 *
 * States: confirmed (both sides name the same port), switch_only, ap_only, conflicting (they disagree),
 * ambiguous (one side names several ports) and unresolved (no evidence).
 */
final class UplinkService {
    private DataGateway $gateway;
    private int $now;

    public function __construct(DataGateway $gateway, int $now) {
        $this->gateway = $gateway;
        $this->now = $now;
    }

    /**
     * @param array $owners hostid => owner (name, site, domain, addresses)
     * @param array $aps    ap_uid => AP
     * @return array{available: bool, reason: ?string, network: ?array, uplinks: array, findings: array, interfaces: array}
     */
    public function build(string $site, array $owners, array $aps): array {
        $empty = ['available'=>false, 'reason'=>null, 'network'=>null, 'uplinks'=>[], 'findings'=>[], 'interfaces'=>[]];
        if ($site === '') {
            return ['reason'=>'site_required'] + $empty;
        }
        $network = (new NetworkService($this->gateway, $this->now))->buildScope(NetworkScope::create([], '', $site));
        if (isset($network['scope']['oversized'])) {
            return ['reason'=>'wired_scope_too_large', 'network'=>$network] + $empty;
        }
        $switches = [];
        foreach ($network['hosts'] as $host) {
            $switches[$host['hostid']] = $host;
        }
        if (!$switches) {
            return ['reason'=>'no_switches', 'network'=>$network] + $empty;
        }
        $interfaces = [];
        foreach ($network['interfaces'] as $interface) {
            $interfaces[$interface['hostid']][$interface['uid']] = $interface;
        }
        // Identity and LLDP of the switches, and the LLDP of AP hosts that carry Network Explorer's LLDP producer.
        $reader = new DatasetReader($this->gateway, $this->now);
        $identity = $reader->read($switches, ['ne.device.snapshot', 'ne.interfaces.inventory', 'ne.lldp.snapshot']);
        $apHosts = [];
        foreach ($owners as $hostid => $owner) {
            if (!isset($switches[$hostid]) && ($owner['observes_ap'] ?? null) !== null) {
                $apHosts[$hostid] = $owner + ['management_addresses'=>$owner['addresses']];
            }
        }
        $apLldp = $apHosts ? $reader->read($apHosts, ['ne.lldp.snapshot'])['datasets'] : [];

        $byMac = [];
        $byAddress = [];
        foreach ($aps as $ap) {
            if ($ap['mac_address'] !== null) {
                $byMac[$ap['mac_address']] = $ap['ap_uid'];
            }
            if ($ap['ip_address'] !== null) {
                $byAddress[$ap['ip_address']][] = $ap['ap_uid'];
            }
        }
        $switchSide = [];
        foreach ($identity['datasets'] as $hostid => $sets) {
            $set = $sets['lldp'] ?? null;
            foreach ($set['data'] ?? [] as $row) {
                $uid = $row['local_interface_uid'] ?? null;
                if (!is_string($uid)) {
                    continue;
                }
                $apUid = null;
                $basis = null;
                $chassis = $row['remote_chassis_id'] ?? [];
                $mac = self::mac((string) ($chassis['value'] ?? ''));
                if (($chassis['subtype'] ?? null) === 4 && $mac !== null && isset($byMac[$mac])) {
                    [$apUid, $basis] = [$byMac[$mac], 'chassis_mac'];
                }
                else {
                    foreach ($row['remote_management_addresses'] ?? [] as $address) {
                        if (is_string($address) && count($byAddress[$address] ?? []) === 1) {
                            [$apUid, $basis] = [$byAddress[$address][0], 'management_address'];
                        }
                    }
                }
                if ($apUid !== null) {
                    $switchSide[$apUid][] = ['hostid'=>(string) $hostid, 'interface_uid'=>$uid, 'basis'=>$basis,
                        'observed_at'=>$set['observed_at'] ?? null, 'freshness'=>$set['freshness'] ?? 'unknown'];
                }
            }
        }
        $apSide = [];
        if ($apLldp) {
            $resolver = new IdentityResolver($switches + $apHosts, $identity['datasets'] + $apLldp);
            foreach ($apLldp as $hostid => $sets) {
                $apUid = $apHosts[$hostid]['observes_ap'];
                foreach ($sets['lldp']['data'] ?? [] as $row) {
                    $resolution = $resolver->resolve($row, (string) $hostid);
                    $apSide[$apUid][] = ['hostid'=>$resolution['status'] === 'resolved' ? $resolution['hostid'] : null,
                        'interface_uid'=>$resolution['interface_uid'] ?? null, 'status'=>$resolution['status'],
                        'evidence'=>$resolution['evidence'] ?? [], 'ap_hostid'=>(string) $hostid,
                        'observed_at'=>$sets['lldp']['observed_at'] ?? null,
                        'freshness'=>$sets['lldp']['freshness'] ?? 'unknown'];
                }
            }
        }

        $uplinks = [];
        $findings = [];
        foreach ($aps as $apUid => $ap) {
            $uplink = $this->correlate($switchSide[$apUid] ?? [], $apSide[$apUid] ?? []);
            if ($uplink['hostid'] !== null) {
                $port = $interfaces[$uplink['hostid']][$uplink['interface_uid']] ?? null;
                $uplink += ['switch_name'=>$switches[$uplink['hostid']]['name'] ?? null,
                    'interface_name'=>$port['name'] ?? null, 'oper_status'=>$port['oper_status'] ?? null,
                    'speed_bps'=>$port['speed_bps'] ?? null, 'vlan'=>$port['vlan'] ?? null,
                    'port_freshness'=>$port['quality']['freshness'] ?? 'unknown',
                    'dashboard_url'=>$port['dashboard_url'] ?? null, 'explorer_url'=>$port['explorer_url'] ?? null];
            }
            $uplinks[$apUid] = $uplink;
            $findings = array_merge($findings, $this->findings($ap, $uplink));
        }
        return ['available'=>true, 'reason'=>null, 'network'=>$network, 'uplinks'=>$uplinks, 'findings'=>$findings,
            'interfaces'=>$interfaces];
    }

    private function correlate(array $switchSide, array $apSide): array {
        $key = static fn(array $o): string => $o['hostid'].'/'.$o['interface_uid'];
        $switchPorts = [];
        foreach ($switchSide as $o) {
            $switchPorts[$key($o)] = $o;
        }
        $apPorts = [];
        foreach ($apSide as $o) {
            if ($o['hostid'] !== null && $o['interface_uid'] !== null) {
                $apPorts[$key($o)] = $o;
            }
        }
        $evidence = array_merge(array_map(static fn($o) => ['side'=>'switch'] + $o, $switchSide),
            array_map(static fn($o) => ['side'=>'ap'] + $o, $apSide));
        $base = ['state'=>'unresolved', 'hostid'=>null, 'interface_uid'=>null, 'basis'=>null, 'observed_at'=>null,
            'freshness'=>'unknown', 'evidence'=>$evidence];
        if (count($switchPorts) > 1 || count($apPorts) > 1) {
            return ['state'=>'ambiguous'] + $base;
        }
        $switch = $switchPorts ? reset($switchPorts) : null;
        $ap = $apPorts ? reset($apPorts) : null;
        if ($switch !== null && $ap !== null) {
            if ($key($switch) !== $key($ap)) {
                return ['state'=>'conflicting'] + $base;
            }
            return ['state'=>'confirmed', 'hostid'=>$switch['hostid'], 'interface_uid'=>$switch['interface_uid'],
                'basis'=>$switch['basis'], 'observed_at'=>$switch['observed_at'],
                'freshness'=>self::worst($switch['freshness'], $ap['freshness'])] + $base;
        }
        if ($switch !== null) {
            return ['state'=>'switch_only', 'hostid'=>$switch['hostid'], 'interface_uid'=>$switch['interface_uid'],
                'basis'=>$switch['basis'], 'observed_at'=>$switch['observed_at'], 'freshness'=>$switch['freshness']] + $base;
        }
        if ($ap !== null) {
            return ['state'=>'ap_only', 'hostid'=>$ap['hostid'], 'interface_uid'=>$ap['interface_uid'],
                'basis'=>'ap_lldp', 'observed_at'=>$ap['observed_at'], 'freshness'=>$ap['freshness']] + $base;
        }
        // AP-side LLDP that names no visible switch port is still evidence of something unresolved.
        return $base;
    }

    private function findings(array $ap, array $uplink): array {
        $label = $ap['name'] ?? $ap['ap_uid'];
        $evidence = array_map(static fn($o) => ['dataset'=>'lldp', 'hostid'=>$o['side'] === 'ap' ? $o['ap_hostid'] : $o['hostid'],
            'observed_at'=>$o['observed_at'], 'fact'=>$o['side'].' side'], $uplink['evidence']);
        switch ($uplink['state']) {
            case 'conflicting':
                return [WifiFinding::create('wifi_uplink_conflict', 'warning', $ap['owner_hostid'], 'ap', $ap['ap_uid'],
                    _s('%1$s: the AP and the switch disagree about its uplink', $label),
                    _('The AP\'s LLDP names one switch port and a switch\'s LLDP names another. One of them is stale or the AP was moved.'),
                    $evidence, $uplink['freshness'], _('Check the cabling and the patch records, then the LLDP data on both sides.'))];
            case 'ambiguous':
                return [WifiFinding::create('wifi_uplink_ambiguous', 'info', $ap['owner_hostid'], 'ap', $ap['ap_uid'],
                    _s('%1$s is seen on more than one switch port', $label),
                    _('Several switch ports report this AP as their LLDP neighbour, so its uplink is not certain.'),
                    $evidence, 'current')];
            case 'unresolved':
                if ($ap['status'] !== 'up') {
                    return [];
                }
                return [WifiFinding::create('wifi_uplink_unresolved', 'info', $ap['owner_hostid'], 'ap', $ap['ap_uid'],
                    _s('%1$s: wired uplink unresolved', $label),
                    _('No visible switch reports this AP over LLDP, and the AP\'s own LLDP is not collected or names no visible switch port. Its VLAN path cannot be checked.'),
                    $evidence, 'unknown',
                    _('Monitor the AP\'s switch with Network Explorer (LLDP), or link Network Explorer\'s LLDP collection to the AP\'s own host.'))];
        }
        return [];
    }

    private static function worst(string $a, string $b): string {
        foreach (['unknown', 'stale', 'current'] as $state) {
            if ($a === $state || $b === $state) {
                return $state;
            }
        }
        return $a;
    }

    private static function mac(string $value): ?string {
        $hex = strtolower(preg_replace('/[^0-9a-fA-F]/', '', $value));
        return strlen($hex) === 12 ? implode(':', str_split($hex, 2)) : null;
    }
}
