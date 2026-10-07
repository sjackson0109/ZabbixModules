<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Spanning-tree overlay from the canonical `stp` dataset: bridges, port roles, and per-link state. */
final class StpService {
    private const PORT_FIELDS = ['instance','role','role_source','state','cost','priority','designated_bridge',
        'designated_port','edge','point_to_point'];
    private const BRIDGE_FIELDS = ['instance','protocol','bridge_id','root_bridge_id','root_cost','root_port_uid',
        'priority','vlans','topology_changes','time_since_topology_change_s'];
    /** A topology change this recent is still settling, or recurring. */
    private const RECENT_CHANGE_S = 3600;

    /** @return array{0: array, 1: array} bridge rows, and port rows keyed by interface uid */
    public static function split(array $rows): array {
        $bridges = [];
        $ports = [];
        foreach ($rows as $row) {
            if (($row['kind'] ?? null) === 'bridge') {
                $bridge = array_intersect_key($row, array_flip(self::BRIDGE_FIELDS));
                $bridge['is_root'] = isset($row['bridge_id']) && $row['bridge_id'] === ($row['root_bridge_id'] ?? null);
                $bridges[] = $bridge;
            }
            elseif (($row['kind'] ?? null) === 'port' && is_string($row['interface_uid'] ?? null)) {
                $ports[$row['interface_uid']][] = array_intersect_key($row, array_flip(self::PORT_FIELDS));
            }
        }
        return [$bridges, $ports];
    }

    /**
     * Adds the instance-0 (CST/CIST) state of both ends to each edge and returns findings.
     * @param array $bridges [hostid] => bridge rows
     * @param array $ports   [hostid][uid] => port rows
     * @param array $domains [hostid] => matching domain
     */
    public static function link(array &$edges, array $bridges, array $ports, array $domains): array {
        $findings = [];
        foreach ($edges as &$edge) {
            $ends = [];
            foreach (['source','target'] as $side) {
                foreach ($ports[$edge[$side] ?? ''][$edge[$side.'_uid'] ?? ''] ?? [] as $row) {
                    if (($row['instance'] ?? null) === 0) {
                        $ends[$side] = ['role'=>$row['role'] ?? 'unknown', 'state'=>$row['state'] ?? 'unknown'];
                    }
                }
            }
            if ($ends) {
                $edge['stp'] = ['source'=>$ends['source'] ?? null, 'target'=>$ends['target'] ?? null,
                    'blocked'=>(bool) array_filter($ends, static fn($end) =>
                        in_array($end['state'], ['blocking','discarding'], true))];
            }
        }
        unset($edge);
        // Within one domain every bridge should agree on the CIST root.
        $roots = [];
        foreach ($bridges as $hostid => $rows) {
            foreach ($rows as $row) {
                if (($row['instance'] ?? null) === 0 && isset($row['root_bridge_id']) && ($domains[$hostid] ?? '') !== '') {
                    $roots[$domains[$hostid]][$row['root_bridge_id']][] = (string) $hostid;
                }
            }
        }
        foreach ($roots as $domain => $byRoot) {
            if (count($byRoot) < 2) {
                continue;
            }
            uasort($byRoot, static fn($a, $b) => count($b) <=> count($a));
            foreach (array_slice($byRoot, 1, null, true) as $root => $hostids) {
                foreach ($hostids as $hostid) {
                    $findings[] = Finding::create('stp_root_disagreement', 'warning', $hostid,
                        'Spanning-tree root differs from its neighbours.',
                        'This switch sees root '.$root.' while most switches in domain '.$domain.' see '
                        .array_key_first($byRoot).'. The network may be split or a bridge priority is wrong.');
                }
            }
        }
        foreach ($bridges as $hostid => $rows) {
            foreach ($rows as $row) {
                $since = $row['time_since_topology_change_s'] ?? null;
                if (is_int($since) && $since < self::RECENT_CHANGE_S && ($row['topology_changes'] ?? 0) > 0) {
                    $findings[] = Finding::create('stp_topology_change', 'info', (string) $hostid,
                        'Recent spanning-tree topology change.',
                        'Instance '.($row['instance'] ?? 0).' changed '.intdiv($since, 60).' minutes ago ('
                        .$row['topology_changes'].' changes since the counter reset).');
                }
            }
        }
        foreach ($ports as $hostid => $byUid) {
            foreach ($byUid as $uid => $rows) {
                foreach ($rows as $row) {
                    if (($row['state'] ?? null) === 'broken') {
                        $findings[] = Finding::create('stp_port_broken', 'warning', (string) $hostid,
                            'Spanning-tree port is broken.', 'Instance '.($row['instance'] ?? 0)
                            .' reports the port as broken; it forwards nothing.', (string) $uid);
                    }
                }
            }
        }
        return $findings;
    }
}
