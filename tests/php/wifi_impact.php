<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\EventService;
use Modules\WifiExplorer\Services\ImpactService;
use Modules\WifiExplorer\Services\PathService;
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

    // Before a switch is chosen, the switches on AP paths are ranked by the APs that would lose service.
    $ranked = (new WifiService(WifiLab::gateway(), WifiLab::now(), WifiLab::config()))
        ->build(WifiScope::create('lab-west', '', ['view'=>'impact']))['wired']['ranking'];
    $assert($ranked !== [] && $ranked[0]['hostid'] === '30' && $ranked[0]['lost'] === 4,
        'The root, on every proven path, ranks first.');
    $lostOrder = array_column($ranked, 'lost');
    $sortedLost = $lostOrder;
    rsort($sortedLost);
    $assert($lostOrder === $sortedLost, 'Switches are ranked by the APs that would lose service.');
    $assert(array_column($ranked, 'lost', 'hostid')['31'] === 2, 'Each rank matches the switch\'s own assessment.');

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

    // A LAG member fails while the other members' "up" is stale: not assessable, never "degraded".
    $gateway = WifiLab::gateway();
    foreach ($gateway->itemRows as $item) {
        if ($item['hostid'] === '31' && $item['key_'] === 'ne.interfaces.state') {
            $envelope = json_decode($gateway->values[$item['itemid']][0]['value'], true);
            $envelope['observed_at'] = $envelope['attempted_at'] = '2026-10-10T09:00:00Z';
            $gateway->values[$item['itemid']] = [['value'=>json_encode($envelope)]];
        }
    }
    $model = (new WifiService($gateway, WifiLab::now(), WifiLab::config()))
        ->build(WifiScope::create('lab-west', '', ['view'=>'impact', 'fail_host'=>'31', 'fail_if'=>$uid('31', 'Te1/0/1')]));
    $stale = array_column($model['impact']['aps'], null, 'ap_uid')[WifiLab::apUid(1)] ?? null;
    $assert($stale !== null && $stale['impact'] === 'cannot_assess' && $stale['reason'] === 'lag_state_unknown',
        'Stale member state cannot prove the LAG still carries traffic.');

    // A whole switch fails: an alternate port leading back to that same switch is no way round it.
    $port = static fn(string $h, string $u, array $stp = [], array $peers = []) => ['hostid'=>$h, 'uid'=>$u, 'name'=>$u,
        'oper_status'=>'up', 'quality'=>['freshness'=>'current'], 'vlan'=>['carried'=>'1-100'], 'stp'=>$stp,
        'explorer_url'=>null, 'peers'=>$peers];
    $network = static fn(string $alternatePeer) => ['hosts'=>[
            ['hostid'=>'1', 'name'=>'A', 'stp'=>[['instance'=>0, 'is_root'=>true, 'root_bridge_id'=>'R']]],
            ['hostid'=>'2', 'name'=>'B', 'stp'=>[['instance'=>0, 'is_root'=>false, 'root_bridge_id'=>'R', 'root_port_uid'=>'b1']]],
            ['hostid'=>'3', 'name'=>'C', 'stp'=>[['instance'=>0, 'is_root'=>false, 'root_bridge_id'=>'R', 'root_port_uid'=>'c1']]]],
        'interfaces'=>[$port('1', 'a1'), $port('1', 'a2'), $port('2', 'ap'),
            $port('2', 'b1', [['instance'=>0, 'role'=>'root']], [['hostid'=>'1']]),
            $port('2', 'b2', [['instance'=>0, 'role'=>'alternate']], [['hostid'=>$alternatePeer]])],
        'edges'=>[['id'=>'e1', 'source'=>'1', 'source_uid'=>'a1', 'target'=>'2', 'target_uid'=>'b1', 'freshness'=>'current']],
        'lags'=>[], 'quality'=>[['hostid'=>'1', 'dataset'=>'stp', 'freshness'=>'current'],
            ['hostid'=>'2', 'dataset'=>'stp', 'freshness'=>'current']]];
    $uplink = ['state'=>'confirmed', 'hostid'=>'2', 'interface_uid'=>'ap', 'freshness'=>'current'];
    $alternate = static function (string $peer) use ($network, $uplink): array {
        $chain = (new PathService($network($peer)))->chain($uplink);
        $aps = ['x'=>['ap_uid'=>'x', 'uplink'=>$uplink, 'chain'=>$chain, 'clients'=>3, 'placement'=>null, 'ssids'=>[]]];
        return [$chain['status'], (new ImpactService($network($peer)))->build('1', '', $aps, [])['aps'][0]['impact']];
    };
    $assert($alternate('1') === ['complete', 'lost'], 'An alternate back to the failed root is no reroute.');
    $assert($alternate('3') === ['complete', 'reroute_possible'], 'An alternate to another switch may reroute.');

    // Event checks on a site whose AP state is unknown, and an SSID that is on at another site only.
    $event = ['event_id'=>'e1', 'name'=>'Conf', 'site'=>'s', 'ssid'=>'Ev', 'starts'=>'2026-10-01T00:00:00Z',
        'ends'=>'2026-12-01T00:00:00Z', 'floors'=>[], 'min_aps'=>null, 'expected_clients'=>100, 'clients_per_ap'=>50];
    $eventAps = [];
    $expectedAps = [];
    foreach (['a', 'b', 'c'] as $apUid) {
        $eventAps[$apUid] = ['ap_uid'=>$apUid, 'name'=>$apUid, 'site'=>'s', 'status'=>'unknown', 'placement'=>null, 'radios'=>[]];
        $expectedAps[] = ['ap_uid'=>$apUid, 'site'=>'s', 'status'=>'unknown', 'reason'=>'ap_state_unknown', 'vlan'=>10];
    }
    $observation = static fn(string $site, bool $enabled, string $freshness) => ['hostid'=>'9', 'owner_name'=>'vc',
        'site'=>$site, 'enabled'=>$enabled, 'hidden'=>false, 'client_count'=>null, 'freshness'=>$freshness, 'observed_at'=>null];
    $readiness = static function (array $observations) use ($event, $eventAps, $expectedAps): array {
        $ssid = ['ssid_uid'=>'x', 'name'=>'Ev', 'declared'=>true, 'enabled'=>null, 'observations'=>$observations,
            'expected'=>$expectedAps];
        $row = (new EventService())->build([$event], [$ssid], $eventAps, [], ['available'=>false, 'reason'=>'not_requested'],
            strtotime('2026-10-12T00:00:00Z'))['events'][0];
        return array_column($row['checks'], 'status', 'check') + ['status'=>$row['status']];
    };
    $unknown = $readiness([$observation('s', true, 'stale')]);
    $assert($unknown['capacity'] === 'unknown' && $unknown['status'] === 'unknown',
        'APs of unknown state make capacity unknown, so the event is unknown, not "not ready".');
    $assert($unknown['utilisation'] === 'not_checked', 'Utilisation nobody measured is not checked, never passed.');
    $elsewhere = $readiness([$observation('s', false, 'current'), $observation('t', true, 'current')]);
    $assert($elsewhere['ssid_enabled'] === 'fail', 'An SSID on at another site only is not enabled for this event.');

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
    $overview = (new WifiService(WifiLab::gateway(), WifiLab::now(), $config))->build(WifiScope::create('lab-west', '', ['view'=>'rf']));
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
