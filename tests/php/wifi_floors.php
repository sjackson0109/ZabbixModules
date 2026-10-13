<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiConfig;
use Modules\WifiExplorer\Services\WifiConfigError;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/** Phase B: configuration, floor plans and overlays, RF neighbours. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $problems = static function ($document): array {
        try {
            WifiConfig::normalise($document);
            return [];
        }
        catch (WifiConfigError $error) {
            return $error->problems;
        }
    };

    // Configuration is validated whole; placement is by opaque AP ID only.
    $config = WifiLab::config();
    $assert(count($config['floors']) === 3 && count($config['placements']) === 4, 'The lab configuration validates.');
    $assert($problems(['placements'=>['00:00:5e:00:53:01'=>['floor_id'=>'x', 'x'=>0, 'y'=>0]]]) !== [],
        'A placement keyed by MAC address is refused.');
    $assert($problems(['floors'=>[['floor_id'=>'a', 'site'=>'s', 'name'=>'A']],
        'placements'=>[WifiLab::apUid(1)=>['floor_id'=>'a', 'x'=>1.5, 'y'=>0]]]) !== [], 'Coordinates are fractions of the plan.');
    $assert($problems(['ssids'=>[['ssid'=>'X', 'vlan'=>4095]]]) !== [], 'A VLAN outside 1-4094 is refused.');
    $assert($problems(['ssids'=>[['ssid'=>'X', 'vlan'=>10, 'psk'=>'secret']]]) !== [],
        'An unknown key (such as a PSK) is refused, not stored.');
    $assert($problems(['events'=>[['event_id'=>'e', 'name'=>'E', 'site'=>'s', 'ssid'=>'Missing',
        'starts'=>'2026-10-20T08:00:00Z', 'ends'=>'2026-10-20T18:00:00Z']]]) !== [], 'An event needs SSID intent.');
    $assert($problems(['events'=>[['event_id'=>'e', 'name'=>'E', 'site'=>'s', 'ssid'=>'X',
        'starts'=>'2026-10-20T18:00:00Z', 'ends'=>'2026-10-20T08:00:00Z']], 'ssids'=>[['ssid'=>'X', 'site'=>'s', 'vlan'=>5]]]) !== [],
        'An event that ends before it starts is refused.');
    $assert($problems(['unknown'=>1, 'floors'=>'x']) !== [] && count($problems(['unknown'=>1, 'floors'=>'x'])) === 2,
        'Every problem is reported at once.');
    $exported = json_decode(json_encode(WifiConfig::export($config)), true);
    $assert(WifiConfig::normalise($exported) === $config, 'The editor\'s document round-trips.');
    $visible = WifiConfig::visible($config, ['lab-west'], [WifiLab::apUid(1)]);
    $assert(count($visible['floors']) === 2 && array_keys($visible['placements']) === [WifiLab::apUid(1)],
        'A viewer sees floors of visible sites and placements of visible APs only.');

    // The floor view: configured positions, observed values, labelled interpolation, unplaced APs listed.
    $gateway = WifiLab::gateway();
    $service = new WifiService($gateway, WifiLab::now(), $config);
    $floors = $service->build(WifiScope::create('lab-west', '', ['view'=>'floors', 'floor'=>'west-ground',
        'overlay'=>'utilisation']));
    $selected = $floors['floors']['selected_floor'];
    $assert(count($floors['floors']['floors']) === 2, 'The other site\'s floor is not offered.');
    $assert(count($selected['markers']) === 3, 'Three APs are placed on the ground floor.');
    $unplaced = $floors['floors']['unplaced'];
    $assert(in_array(WifiLab::apUid(3), $unplaced, true) && in_array(WifiLab::apUid(6), $unplaced, true)
        && count($unplaced) === 2, 'APs without placement are listed, never dropped.');
    $assert($selected['legend']['kind'] === 'interpolated' && strpos($selected['legend']['text'], 'not a predictive RF survey') !== false,
        'The utilisation field says it is interpolation, not a survey.');
    $assert($selected['field'] !== null && $selected['field']['cells'] !== [], 'The field is drawn near the APs.');
    $markers = array_column($selected['markers'], null, 'ap_uid');
    $assert($markers[WifiLab::apUid(2)]['utilisation'] === 82, 'Marker values are the observed ones.');
    $assert(abs($markers[WifiLab::apUid(4)]['y'] - 0.35) < 1e-9, 'Positions use the plan\'s proportions.');
    $retries = $service->build(WifiScope::create('lab-west', '', ['view'=>'floors', 'floor'=>'west-ground',
        'overlay'=>'retries']))['floors']['selected_floor'];
    $assert($retries['legend']['kind'] === 'not_collected' && $retries['field'] === null,
        'An overlay the source cannot feed draws nothing and says why.');
    $clients = $service->build(WifiScope::create('lab-west', '', ['view'=>'floors', 'floor'=>'west-ground',
        'overlay'=>'clients']))['floors']['selected_floor'];
    $assert(array_column($clients['markers'], 'clients', 'ap_uid')[WifiLab::apUid(1)] === 3,
        'Client density uses the observed client count per AP.');
    $missing = $service->build(WifiScope::create('lab-west', '', ['view'=>'floors', 'floor'=>'east-ground']));
    $assert($missing['floors']['floor_missing'] && $missing['floors']['selected_floor'] === null,
        'A floor of another site selects nothing and says so.');

    // Channel reuse is drawn only as reuse unless RF evidence shows one AP hearing the other.
    $channels = $service->build(WifiScope::create('lab-west', '', ['view'=>'floors', 'floor'=>'west-ground',
        'overlay'=>'channel']))['floors']['selected_floor'];
    $assert(array_filter($channels['reuse'], static fn($p) => !$p['heard']) === $channels['reuse'],
        'No two placed APs on one channel hear each other in the lab, so every pair is reuse only.');

    // RF neighbours: observer attribution, managed and external classes, the AP's own labels kept.
    $rf = $floors['rf'];
    $observers = array_column($rf['observers'], null, 'hostid');
    $assert($observers['20']['ap_uid'] === WifiLab::apUid(1) && $observers['20']['basis'] === 'host_name',
        'The RF host is matched to its AP (by host name here; by polled address when they match).');
    $assert($observers['10']['ap_uid'] === null, 'Detections polled through the VC address are not pinned to an AP.');
    $byBssid = [];
    foreach ($rf['neighbours'] as $row) {
        $byBssid[$row['bssid']] = $row;
    }
    $assert($byBssid['00:00:5e:00:53:89']['class'] === 'managed' && $byBssid['00:00:5e:00:53:89']['class_basis'] === 'observed'
        && $byBssid['00:00:5e:00:53:89']['managed_ap_uid'] === WifiLab::apUid(2), 'A managed radio is recognised.');
    $assert($byBssid['00:00:5e:00:53:f4']['class'] === 'known_external' && $byBssid['00:00:5e:00:53:f4']['known_label']
        === 'Neighbouring office', 'An operator-listed BSSID is known external.');
    $assert($byBssid['00:00:5e:00:53:f2']['class'] === 'flagged' && isset($byBssid['00:00:5e:00:53:f2']['labels']['suspected_unsecure']),
        'The AP\'s own classification is kept.');
    $assert($byBssid['00:00:5e:00:53:f3']['class'] === 'unknown', 'Unknown stays unknown.');
    $assert(count($byBssid['00:00:5e:00:53:f1']['observers']) === 2, 'A BSSID heard by two APs is one row with two observers.');
    $flagged = array_values(array_filter($floors['findings'], static fn($f) => $f['rule'] === 'wifi_rf_flagged'));
    $assert(count($flagged) === 1 && stripos(json_encode($floors), 'malicious') === false,
        'A flagged network is one finding and nothing is called malicious.');
    $contention = array_values(array_filter($floors['findings'], static fn($f) => $f['rule'] === 'wifi_co_channel_external'));
    $assert(count($contention) === 1 && $contention[0]['object_id'] !== null,
        'lab-ap-01 hears CoffeeShop strongly on its own channel 36: contention backed by RF evidence.');

    // A viewer who cannot read the RF host sees no detections from it.
    $hidden = (new WifiService(WifiLab::gateway(['20']), WifiLab::now(), $config))->build(WifiScope::create('lab-west'));
    $assert(!isset(array_column($hidden['rf']['observers'], null, 'hostid')['20']), 'An unreadable RF host contributes nothing.');

    echo "Wi-Fi floor and RF checks passed ($checks checks).\n";
})();
