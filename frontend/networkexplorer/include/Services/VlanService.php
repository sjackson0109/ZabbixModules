<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** VLAN membership per port and per link, from the canonical `vlan` dataset. */
final class VlanService {
    /** Expands a canonical range string ("1,10-12") into sorted VLAN IDs. */
    public static function expand(?string $ranges): array {
        $result = [];
        foreach (explode(',', (string) $ranges) as $part) {
            if ($part === '') {
                continue;
            }
            [$low, $high] = array_pad(explode('-', $part, 2), 2, null);
            $low = (int) $low;
            $high = $high === null ? $low : (int) $high;
            for ($id = max(1, $low); $id <= min(4094, $high); ++$id) {
                $result[$id] = true;
            }
        }
        $result = array_keys($result);
        sort($result);
        return $result;
    }

    public static function compress(array $ids): string {
        sort($ids);
        $parts = [];
        $start = $prev = null;
        foreach ($ids as $id) {
            if ($prev !== null && $id === $prev + 1) {
                $prev = $id;
                continue;
            }
            if ($start !== null) {
                $parts[] = $start === $prev ? (string) $start : $start.'-'.$prev;
            }
            $start = $prev = $id;
        }
        if ($start !== null) {
            $parts[] = $start === $prev ? (string) $start : $start.'-'.$prev;
        }
        return implode(',', $parts);
    }

    /** Browser view of one port row; `carried` is what the port actually sends now. */
    public static function port(array $row): array {
        $current = self::expand($row['current_egress'] ?? '');
        $static = array_merge(self::expand($row['tagged'] ?? ''), self::expand($row['untagged'] ?? ''));
        $carried = $current ?: array_values(array_unique($static));
        $untagged = self::expand($row['current_untagged'] ?? '') ?: self::expand($row['untagged'] ?? '');
        return ['mode'=>$row['mode'] ?? 'unknown', 'pvid'=>is_int($row['pvid'] ?? null) ? $row['pvid'] : null,
            'tagged'=>self::compress(array_values(array_diff($carried, $untagged))),
            'untagged'=>self::compress(array_values(array_intersect($untagged, $carried))),
            'forbidden'=>self::compress(self::expand($row['forbidden'] ?? '')),
            'carried'=>self::compress($carried)];
    }

    /**
     * Adds a `vlan` summary to each edge whose two ends both report membership, and returns findings.
     * @param array $ports [hostid][uid] => port() view
     * @param array $lldp  [hostid][uid] => LLDP row, for peers without VLAN data of their own
     * @param array $labels [hostid][uid] => "host port", for finding text
     */
    public static function link(array &$edges, array $ports, array $lldp, array $labels = []): array {
        $findings = [];
        $covered = [];
        foreach ($edges as &$edge) {
            $a = $ports[$edge['source'] ?? ''][$edge['source_uid'] ?? ''] ?? null;
            $b = $ports[$edge['target'] ?? ''][$edge['target_uid'] ?? ''] ?? null;
            if ($a === null || $b === null) {
                continue;
            }
            $covered[$edge['source']][$edge['source_uid']] = $covered[$edge['target']][$edge['target_uid']] = true;
            $carriedA = self::expand($a['carried']);
            $carriedB = self::expand($b['carried']);
            $edge['vlan'] = ['source_pvid'=>$a['pvid'], 'target_pvid'=>$b['pvid'],
                'common'=>self::compress(array_values(array_intersect($carriedA, $carriedB))),
                'source_only'=>self::compress(array_values(array_diff($carriedA, $carriedB))),
                'target_only'=>self::compress(array_values(array_diff($carriedB, $carriedA)))];
            $nameA = $labels[$edge['source']][$edge['source_uid']] ?? 'one end';
            $nameB = $labels[$edge['target']][$edge['target_uid']] ?? 'the other end';
            if ($a['pvid'] !== null && $b['pvid'] !== null && $a['pvid'] !== $b['pvid']) {
                $findings[] = self::finding('native_vlan_mismatch', 'warning', $edge, 'Native VLAN differs across a link.',
                    'Native VLAN '.$a['pvid'].' on '.$nameA.' and '.$b['pvid'].' on '.$nameB.'; untagged traffic changes VLAN.');
            }
            if ($edge['vlan']['source_only'] !== '' || $edge['vlan']['target_only'] !== '') {
                $parts = [];
                foreach ([[$edge['vlan']['source_only'], $nameA, $nameB], [$edge['vlan']['target_only'], $nameB, $nameA]]
                        as [$only, $has, $lacks]) {
                    if ($only !== '') {
                        $parts[] = 'VLAN '.self::cap($only).' is carried by '.$has.' but not permitted on '.$lacks;
                    }
                }
                $findings[] = self::finding('vlan_not_carried', 'info', $edge, 'A VLAN stops at this link.',
                    implode('; ', $parts).'.');
            }
        }
        unset($edge);
        // Peers without VLAN data (unmonitored or unresolved) still advertise their native VLAN over LLDP.
        foreach ($lldp as $hostid => $rows) {
            foreach ($rows as $uid => $row) {
                $local = $ports[$hostid][$uid]['pvid'] ?? null;
                $remote = $row['remote_pvid'] ?? null;
                if (!isset($covered[$hostid][$uid]) && is_int($local) && is_int($remote) && $local !== $remote) {
                    $findings[] = ['id'=>hash('sha256', $hostid.'|'.$uid.'|native_vlan_mismatch'), 'hostid'=>(string) $hostid,
                        'interface_uid'=>(string) $uid, 'severity'=>'warning', 'rule'=>'native_vlan_mismatch',
                        'title'=>'Native VLAN differs across a link.',
                        'reason'=>'Native VLAN '.$local.' here; the LLDP neighbour reports '.$remote.'.'];
                }
            }
        }
        return $findings;
    }

    private static function cap(string $text): string {
        return strlen($text) > 120 ? substr($text, 0, 117).'...' : $text;
    }

    private static function finding(string $rule, string $severity, array $edge, string $title, string $reason): array {
        return ['id'=>$rule.':'.$edge['id'], 'hostid'=>(string) $edge['source'], 'interface_uid'=>$edge['source_uid'],
            'edge_id'=>$edge['id'], 'severity'=>$severity, 'rule'=>$rule, 'title'=>$title, 'reason'=>$reason];
    }
}
