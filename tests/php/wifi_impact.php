<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/** Phase E: blast radius of a wired failure, and event readiness. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $uid = static function (string $hostid, string $name): string {
        $model = (new WifiService(WifiLab::gateway(), WifiLab::now(), WifiLab::config()))
            ->build(WifiScope::create('lab-west', '', ['view'=>'impact', 'fail_host'=>$hostid]));
        return array_column($model['wired']['interfaces'], 'uid', 'name')[$name];
    };
    $impact = static function (string $hostid, string $interface = '', ?array $config = null, array $omit = []): array {
        $model = (new WifiService(WifiLab::gateway($omit), WifiLab::now(), $config ?? WifiLab::config()))
            ->build(WifiScope::create('lab-west', '', ['view'=>'impact', 'fail_host'=>$hostid, 'fail_if'=>$interface]));
        $model['by_ap'] = array_column($model['impact']['aps'] ?? [], null, 'ap_uid');
        return $model;
    };

    // The access switch: its own APs lose service, the other switch's APs are unaffected.
    $access = $impact('31');
    $assert($access['impact']['counts']['lost'] === 2 && $access['by_ap'][WifiLab::apUid(1)]['reason'] === 'ap_switch',
        'lab-ap-01 and lab-ap-02 lose their own switch.');
    $assert(!isset($access['by_ap'][WifiLab::apUid(4)]) && $access['impact']['unaffected'] === 2,
        'APs on sw-wifi-access-02 are unaffected.');
    $assert($access['by_ap'][WifiLab::apUid(6)]['impact'] === 'cannot_assess',
        'An AP without an uplink cannot be assessed, never reported as unaffected.');
    $assert($access['impact']['clients'] === ['estimated'=>5, 'aps_without_count'=>0, 'kind'=>'estimated'],
        'Clients associated now are counted as an estimate.');
    $assert($access['impact']['vlans'] === [49, 56, 57] && $access['impact']['floors'] === ['west-ground'=>2],
        'VLANs of broadcasting SSIDs and floors of the lost APs.');
    $guest = array_column($access['impact']['ssids'], null, 'name')['Lab-Guest'];
    $assert($guest['lost'] === 2 && $guest['broadcasting'] === 3 && !$guest['all_lost'], 'Lab-Guest loses 2 of 3 APs.');

    // The root bridge: everything with a known path depends on it.
    $root = $impact('30');
    $assert($root['impact']['target']['is_root'] && $root['impact']['counts']['lost'] === 4, 'The root takes down every proven path.');
    $assert(array_column($root['impact']['ssids'], 'all_lost', 'name') === ['Lab-Corp'=>true, 'Lab-Event'=>true, 'Lab-Guest'=>true],
        'Every SSID loses all its broadcasting APs.');

    // A LAG member: degraded while another member is up; the whole LAG: lost.
    $member = $impact('31', $uid('31', 'Te1/0/1'));
    $assert($member['impact']['target']['lag_member_of'] === 'Po1'
        && $member['by_ap'][WifiLab::apUid(1)]['impact'] === 'degraded' && $member['impact']['counts']['lost'] === 0,
        'One LAG member failing degrades the path.');
    $lag = $impact('30', $uid('30', 'Po1'));
    $assert($lag['by_ap'][WifiLab::apUid(1)]['impact'] === 'lost' && $lag['by_ap'][WifiLab::apUid(1)]['at_hop'] === 2,
        'The whole LAG on the root side cuts lab-ap-01 at hop 3.');

    // An AP port: only that AP.
    $port = $impact('32', $uid('32', 'Gi1/0/1'));
    $assert(array_keys(array_filter($port['by_ap'], static fn($a) => $a['impact'] === 'lost')) === [WifiLab::apUid(4)],
        'An AP\'s own port affects that AP only.');

    // An STP alternate below the failure is offered, not assumed.
    $gateway = WifiLab::gateway();
    foreach ($gateway->itemRows as $item) {
        if ($item['hostid'] === '31' && $item['key_'] === 'ne.stp.snapshot') {
            $envelope = json_decode($gateway->values[$item['itemid']][0]['value'], true);
            foreach ($envelope['data'] as &$row) {
                if (($row['kind'] ?? '') === 'port' && ($row['state'] ?? '') === 'forwarding' && ($row['role'] ?? '') === 'designated'
                        && ($row['instance'] ?? null) === 0 && !isset($done)) {
                    [$row['role'], $row['state'], $done] = ['alternate', 'discarding', true];
                }
            }
            unset($row);
            $gateway->values[$item['itemid']] = [['value'=>json_encode($envelope)]];
        }
    }
    $model = (new WifiService($gateway, WifiLab::now(), WifiLab::config()))
        ->build(WifiScope::create('lab-west', '', ['view'=>'impact', 'fail_host'=>'30', 'fail_if'=>$uid('30', 'Po1')]));
    $ap2 = array_column($model['impact']['aps'], null, 'ap_uid')[WifiLab::apUid(2)];
    $assert($ap2['impact'] === 'reroute_possible' && $ap2['alternates'] !== [] && $ap2['alternates'][0]['carried'] !== null,
        'A switch below the failure with an up STP alternate may reroute; the alternate\'s VLANs are shown.');

    // Not visible: nothing is disclosed about a switch the viewer cannot read.
    $hidden = $impact('31', '', null, ['31']);
    $assert($hidden['impact']['status'] === 'not_visible' && $hidden['impact']['target'] === null,
        'A hidden switch is not assessed.');

    // Event readiness: built from Phases A-D, credentials never passed.
    $model = (new WifiService(WifiLab::gateway(), WifiLab::now(), WifiLab::config()))
        ->build(WifiScope::create('lab-west', '', ['view'=>'events']));
    $expo = $model['events'][0];
    $checksBy = array_column($expo['checks'], 'status', 'check');
    $assert($expo['timing'] === 'upcoming' && $expo['status'] === 'not_ready', 'Expo is upcoming and not ready.');
    $assert($checksBy['ssid_enabled'] === 'pass' && $checksBy['aps_up'] === 'pass' && $checksBy['broadcasting'] === 'pass',
        'The SSID is on and enough APs are up and broadcasting.');
    $assert($checksBy['vlan_paths'] === 'fail' && $checksBy['capacity'] === 'fail',
        'lab-ap-04\'s failed VLAN path leaves 3 serving APs: paths and declared capacity fail.');
    $assert($checksBy['credentials'] === 'not_checked' && $checksBy['utilisation'] === 'warn', 'Credentials are never passed.');
    $assert(count(array_filter($model['findings'], static fn($f) => $f['rule'] === 'wifi_event_not_ready')) === 1,
        'A not-ready upcoming event is a warning.');

    // Fix the VLAN on paper (declare min_aps 3): ready apart from nothing unknown.
    $config = WifiLab::config();
    $config['events'][0]['min_aps'] = 3;
    $config['events'][0]['expected_clients'] = 90;
    $ready = (new WifiService(WifiLab::gateway(), WifiLab::now(), $config))->build(WifiScope::create('lab-west', '', ['view'=>'events']));
    $assert($ready['events'][0]['status'] === 'ready', 'With three serving APs required, Expo is ready.');

    // Without the wired model the paths are unknown, so the event is unknown, and no finding claims otherwise.
    $overview = (new WifiService(WifiLab::gateway(), WifiLab::now(), $config))->build(WifiScope::create('lab-west', '', []));
    $assert($overview['events'][0]['status'] === 'unknown'
        && !array_filter($overview['findings'], static fn($f) => strpos($f['rule'], 'wifi_event_') === 0),
        'Unproven paths make readiness unknown, never ready.');

    // An event on a floor with no placed AP.
    $config = WifiLab::config();
    $config['events'][0]['floors'] = ['west-first'];
    $config['events'][0]['min_aps'] = 2;
    $floor = (new WifiService(WifiLab::gateway(), WifiLab::now(), $config))->build(WifiScope::create('lab-west', '', ['view'=>'events']));
    $assert($floor['events'][0]['aps'] === [WifiLab::apUid(5)]
        && array_column($floor['events'][0]['checks'], 'status', 'check')['aps_up'] === 'fail',
        'Event floors narrow the serving APs; one AP cannot meet a minimum of two.');

    echo "Wi-Fi impact and event checks passed ({$checks} checks).\n";
})();
