<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/** Phase D: VLAN service paths from the AP's port to the spanning-tree root, first failing hop named. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    // Rewrites one host's latest envelope of one item.
    $mutate = static function (FixtureGateway $gateway, string $hostid, string $key, callable $change): void {
        foreach ($gateway->itemRows as $item) {
            if ($item['hostid'] === $hostid && $item['key_'] === $key) {
                $envelope = json_decode($gateway->values[$item['itemid']][0]['value'], true);
                $gateway->values[$item['itemid']] = [['value'=>json_encode($change($envelope))]];
            }
        }
    };
    $paths = static function (?FixtureGateway $gateway = null): array {
        $model = (new WifiService($gateway ?? WifiLab::gateway(), WifiLab::now(), WifiLab::config()))
            ->build(WifiScope::create('lab-west', '', ['view'=>'paths']));
        $byName = [];
        foreach ($model['paths'] as $path) {
            $byName[$path['name']] = $path;
        }
        return [$byName, $model];
    };
    $result = static fn(array $paths, string $ssid, int $ap): ?array => $paths[$ssid]['results'][WifiLab::apUid($ap)] ?? null;
    $stp = static function (array $envelope, callable $row): array {
        $envelope['data'] = array_map($row, $envelope['data']);
        return $envelope;
    };

    [$lab, $model] = $paths();
    $assert($result($lab, 'Lab-Corp', 1)['status'] === 'complete', 'VLAN 49 reaches the root from lab-ap-01 over the LAG.');
    $hops = $result($lab, 'Lab-Corp', 1)['hops'];
    $assert(array_column($hops, 'role') === ['access', 'root_port', 'designated']
        && $hops[1]['interface_name'] === 'Po1' && count($hops[1]['lag_members']) === 2,
        'The path follows the access switch\'s root port, a LAG, to the root bridge.');
    $assert($hops[0]['tagging'] === 'untagged', 'VLAN 49 is the AP port\'s native VLAN.');
    $event4 = $result($lab, 'Lab-Event', 4);
    $assert($event4['status'] === 'failed' && $event4['failed_hop'] === 0 && $event4['reason'] === 'vlan_not_on_ap_port',
        'lab-ap-04 fails at its own switch port for the event VLAN.');
    $guest1 = $result($lab, 'Lab-Guest', 1);
    $assert($guest1['status'] === 'failed' && $guest1['failed_hop'] === 2 && $guest1['hops'][2]['switch_name'] === 'sw-wifi-dist-01'
        && $guest1['hops'][2]['interface_name'] === 'Po1', 'VLAN 57 stops at the distribution switch\'s Po1.');
    $assert($result($lab, 'Lab-Guest', 4)['status'] === 'complete', 'VLAN 57 reaches the root from lab-ap-04.');
    $assert($result($lab, 'Lab-Corp', 6)['status'] === 'unknown' && $result($lab, 'Lab-Corp', 6)['reason'] === 'uplink_unresolved',
        'An AP without an uplink has an unknown path, never a complete one.');
    $failed = array_values(array_filter($model['findings'], static fn($f) => $f['rule'] === 'wifi_path_failed'));
    $assert(count($failed) === 3, 'One warning per SSID and failing trunk; access ports are grouped per SSID.');
    $assert($lab['Lab-Guest']['counts'] === ['complete'=>1, 'failed'=>2, 'partial'=>0, 'unknown'=>0], 'Counts per SSID.');

    // Stale spanning-tree data on the access switch: the walk stops; nothing upstream is claimed.
    $gateway = WifiLab::gateway();
    $mutate($gateway, '31', 'ne.stp.snapshot', static fn($e) => ['observed_at'=>'2026-10-12T09:00:00Z',
        'attempted_at'=>'2026-10-12T09:00:00Z'] + $e);
    [$stale] = $paths($gateway);
    $assert($result($stale, 'Lab-Corp', 1)['status'] === 'partial' && $result($stale, 'Lab-Corp', 1)['reason'] === 'stp_stale',
        'Stale STP makes the path partial.');
    $assert($result($stale, 'Lab-Guest', 1)['status'] === 'partial',
        'With the walk stopped, the dist Po1 failure is not reached either.');

    // Blocking on the uplink to the root.
    $gateway = WifiLab::gateway();
    $mutate($gateway, '32', 'ne.stp.snapshot', static fn($e) => $stp($e, static fn($row) => ($row['kind'] ?? '') === 'port'
        && ($row['state'] ?? '') === 'forwarding' && ($row['role'] ?? '') === 'root' ? ['state'=>'blocking'] + $row : $row));
    [$blocked] = $paths($gateway);
    $assert($result($blocked, 'Lab-Corp', 4)['reason'] === 'stp_blocking' && $result($blocked, 'Lab-Corp', 4)['failed_hop'] === 1,
        'A blocking root port fails the path at that hop.');

    // Bridges that disagree about the root.
    $gateway = WifiLab::gateway();
    $mutate($gateway, '32', 'ne.stp.snapshot', static fn($e) => $stp($e, static fn($row) => ($row['kind'] ?? '') === 'bridge'
        ? ['root_bridge_id'=>'0000aabbccddeeff'] + $row : $row));
    $mutate($gateway, '30', 'ne.stp.snapshot', static fn($e) => $e);
    [$disagree] = $paths($gateway);
    $assert(in_array($result($disagree, 'Lab-Corp', 4)['status'], ['partial', 'unknown'], true)
        && $result($disagree, 'Lab-Corp', 4)['status'] !== 'complete', 'Root disagreement never yields a complete path.');

    // A hidden upstream switch: the path stops at the last visible port.
    [$hidden] = $paths(WifiLab::gateway(['30']));
    $assert($result($hidden, 'Lab-Corp', 1)['status'] === 'partial', 'Without the root switch, paths are partial.');

    // Stale VLAN data at the AP's switch: unknown at that hop.
    $gateway = WifiLab::gateway();
    $mutate($gateway, '31', 'ne.vlan.snapshot', static fn($e) => ['observed_at'=>'2026-10-12T09:00:00Z',
        'attempted_at'=>'2026-10-12T09:00:00Z'] + $e);
    [$vlanStale] = $paths($gateway);
    $assert($result($vlanStale, 'Lab-Corp', 1)['status'] === 'unknown'
        && $result($vlanStale, 'Lab-Corp', 1)['reason'] === 'vlan_data_stale', 'Stale VLAN data is unknown, not complete.');
    $assert($result($vlanStale, 'Lab-Guest', 1)['status'] === 'failed' && $result($vlanStale, 'Lab-Guest', 1)['uncertain_before'],
        'A later definite failure is still named, with the earlier uncertainty flagged.');

    // MSTP: a VLAN mapped to another instance is not proven by the CIST walk.
    $gateway = WifiLab::gateway();
    foreach (['30', '31'] as $hostid) {
        $mutate($gateway, $hostid, 'ne.stp.snapshot', static function ($e) {
            foreach ($e['data'] as &$row) {
                if (($row['kind'] ?? '') === 'bridge') {
                    $row['protocol'] = 'mstp';
                    $extra = ['instance'=>1, 'vlans'=>'56'] + $row;
                }
            }
            unset($row);
            $e['data'][] = $extra;
            return $e;
        });
    }
    [$mstp] = $paths($gateway);
    $assert($result($mstp, 'Lab-Event', 1)['status'] === 'partial' && $result($mstp, 'Lab-Event', 1)['reason'] === 'mstp_instance',
        'A VLAN in another MSTP instance is partial.');
    $assert($result($mstp, 'Lab-Corp', 1)['status'] === 'complete'
        && in_array('mstp_cist_only', $result($mstp, 'Lab-Corp', 1)['caveats'], true), 'A CIST VLAN is complete, with the caveat.');

    echo "Wi-Fi VLAN path checks passed ({$checks} checks).\n";
})();
