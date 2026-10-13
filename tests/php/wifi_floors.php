<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiConfig;
use Modules\WifiExplorer\Services\ChannelPlan;
use Modules\WifiExplorer\Services\RfService;
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
    $assert(WifiConfig::normalise(WifiConfig::stored($config)) === $config && $config['ssids'] !== [],
        'What is saved loads again: the stored form is the document, not the normalised form with derived SSID IDs.');
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

    // Detections only in a stale RF snapshot are listed as stale and not counted as heard now.
    $staleRf = WifiLab::gateway();
    foreach ($staleRf->itemRows as $item) {
        if ($item['key_'] === 'we.rf.neighbour') {
            $envelope = json_decode($staleRf->values[$item['itemid']][0]['value'], true);
            $envelope['observed_at'] = $envelope['attempted_at'] = '2026-10-10T09:00:00Z';
            $staleRf->values[$item['itemid']] = [['value'=>json_encode($envelope)]];
        }
    }
    $old = (new WifiService($staleRf, WifiLab::now(), $config))->build(WifiScope::create('lab-west'))['rf'];
    $assert($old['current_total'] + $old['stale'] === $old['total'] && $old['stale'] > 0
        && array_sum($old['counts']) === $old['current_total'] && $old['neighbours'][0]['last_seen'] !== null,
        'Stale detections are counted apart from what is heard now, with when they were last seen.');

    // A viewer who cannot read the RF host sees no detections from it.
    $hidden = (new WifiService(WifiLab::gateway(['20']), WifiLab::now(), $config))->build(WifiScope::create('lab-west'));
    $assert(!isset(array_column($hidden['rf']['observers'], null, 'hostid')['20']), 'An unreadable RF host contributes nothing.');

    // Event times are checked field by field: an impossible date is refused, never rolled into the next month.
    $timeProblem = static fn(string $starts) => (bool) array_filter($problems(['version'=>1, 'events'=>[[
        'event_id'=>'e', 'name'=>'E', 'site'=>'s', 'ssid'=>'S', 'starts'=>$starts, 'ends'=>'2030-01-01T00:00:00Z']]]),
        static fn($p) => strpos($p, 'starts must be a UTC time') !== false);
    $assert($timeProblem('2026-02-30T08:00:00Z') && $timeProblem('2026-10-20T24:00:00Z'),
        '30 February and hour 24 are refused.');
    $assert(!$timeProblem('2028-02-29T08:00:00Z'), 'A real leap day is accepted.');

    // The editor's AP list comes from inventory alone and says which APs are placed.
    $directory = array_column($service->apDirectory(), null, 'ap_uid');
    $assert(count($directory) === count($floors['aps']) && $directory[WifiLab::apUid(1)]['placed']
        && !$directory[WifiLab::apUid(3)]['placed'], 'The editor lists every AP and its placement.');

    // Co-channel contention needs the same band; an AP's own extra SSIDs are not neighbours.
    $radio = ['radio_uid'=>'r1', 'radio_index'=>0, 'status'=>'up', 'channel'=>1, 'band'=>'2.4',
        'bssid'=>'aa:bb:cc:dd:ee:10'];
    $aps = ['ap-a'=>['ap_uid'=>'ap-a', 'name'=>'ap-a', 'ip_address'=>null, 'radios'=>[$radio]]];
    $detection = static fn(string $bssid, string $band) => ['bssid'=>$bssid, 'ssid'=>'N', 'channel'=>1, 'band'=>$band,
        'channel_width'=>null, 'encryption'=>null, 'snr_db'=>40, 'classification'=>'interfering',
        'classification_raw'=>null];
    $rfModel = (new RfService())->build(['7'=>['hostid'=>'7', 'name'=>'ap-a', 'addresses'=>[]]],
        ['7'=>['rf_neighbour'=>['freshness'=>'current', 'observed_at'=>null, 'warnings'=>[],
            'data'=>[$detection('aa:bb:cc:dd:ee:11', '2.4'), $detection('02:00:00:00:00:01', '6')]]]], $aps, []);
    $assert($rfModel['total'] === 1 && $rfModel['neighbours'][0]['bssid'] === '02:00:00:00:00:01',
        'The AP\'s own second SSID is not listed as a neighbour.');
    $assert(!array_filter($rfModel['findings'], static fn($f) => strpos($f['rule'], 'wifi_co_channel') === 0),
        'A 6 GHz network on channel 1 does not contend with a 2.4 GHz radio on channel 1.');

    // Large sites: a document too big to store as it is is packed, and comes back identical.
    $assert(WifiConfig::pack($config) === WifiConfig::stored($config), 'A small document is stored as it is.');
    $big = ['floors'=>[], 'placements'=>[], 'ssids'=>[['ssid'=>'Corp', 'site'=>'site-0', 'vlan'=>10]]];
    for ($f = 0; $f < 40; ++$f) {
        $big['floors'][] = ['floor_id'=>'floor-'.$f, 'site'=>'site-'.($f % 8), 'name'=>'Floor '.$f, 'width_m'=>80.5];
    }
    mt_srand(7);
    for ($i = 0; $i < 2000; ++$i) {
        $big['placements']['ap-'.substr(hash('sha256', 'ap'.$i), 0, 24)] = ['floor_id'=>'floor-'.($i % 40),
            'x'=>round(mt_rand(0, 100000) / 100000, 5), 'y'=>$i === 0 ? 1 : round(mt_rand(0, 100000) / 100000, 5)];
    }
    $bigConfig = WifiConfig::normalise($big);
    $packed = WifiConfig::pack($bigConfig);
    $assert(is_string($packed) && strlen(json_encode($bigConfig)) > 2 * WifiConfig::MAX_STORED_BYTES
        && strlen(json_encode($packed)) <= WifiConfig::MAX_STORED_BYTES,
        'Two thousand placements, too large as they are, fit once packed.');
    $assert(WifiConfig::normalise(WifiConfig::unpack($packed)) === $bigConfig, 'A packed document round-trips exactly.');
    for ($i = 2000; $i < 3200; ++$i) {
        $big['placements']['ap-'.substr(hash('sha256', 'ap'.$i), 0, 24)] = ['floor_id'=>'floor-0', 'x'=>mt_rand(0, 100000) / 100000,
            'y'=>mt_rand(0, 100000) / 100000];
    }
    $tooBig = $problems($big);
    $assert(count($tooBig) === 1 && strpos($tooBig[0], 'once packed') !== false,
        'A document that does not fit even packed is refused with its size, before anything is saved.');
    $damaged = static function ($stored): bool {
        try {
            WifiConfig::unpack($stored);
            return false;
        }
        catch (WifiConfigError $error) {
            return true;
        }
    };
    $assert($damaged('wifi-z1:'.substr($packed, 8, 200)) && $damaged('not packed') && $damaged('wifi-z1:%%%'),
        'A damaged packed document is refused, never half-read.');

    // Overlapping channels, from the channel plan: inferred, never on a channel that does not share spectrum.
    $assert(ChannelPlan::span('5', 36, '80') === [5170, 5250, 'block'] && ChannelPlan::span('5', 112, '40') === [5530, 5570, 'block']
        && ChannelPlan::span('6', 37, '160') === [6105, 6265, 'block'] && ChannelPlan::span('2.4', 6, '40')[2] === 'primary'
        && ChannelPlan::span('5', 36, null)[2] === 'primary' && ChannelPlan::span('2.4', 36, '20') === null,
        'The channel plan gives the bonded block, or only the primary when the block is not fixed.');
    $overlap = static function (string $band, int $own, ?string $ownWidth, int $theirs, ?string $width, int $snr = 40) use ($aps): array {
        $radio = ['radio_uid'=>'r1', 'radio_index'=>0, 'status'=>'up', 'channel'=>$own, 'band'=>$band,
            'channel_width'=>$ownWidth, 'bssid'=>'aa:bb:cc:dd:ee:10'];
        $model = (new RfService())->build(['7'=>['hostid'=>'7', 'name'=>'ap-a', 'addresses'=>[]]],
            ['7'=>['rf_neighbour'=>['freshness'=>'current', 'observed_at'=>null, 'warnings'=>[], 'data'=>[[
                'bssid'=>'02:00:00:00:00:09', 'ssid'=>'N', 'channel'=>$theirs, 'band'=>$band, 'channel_width'=>$width,
                'encryption'=>null, 'snr_db'=>$snr, 'classification'=>'interfering', 'classification_raw'=>null]]]]],
            ['ap-a'=>['radios'=>[$radio]] + $aps['ap-a']], []);
        return array_values(array_filter($model['findings'], static fn($f) => $f['rule'] === 'wifi_channel_overlap'));
    };
    $found = $overlap('2.4', 1, '20', 3, '20');
    $assert(count($found) === 1 && $found[0]['confidence'] === 'inferred' && $found[0]['severity'] === 'info',
        '2.4 GHz channels 1 and 3 overlap: an inferred finding.');
    $assert(!$overlap('2.4', 1, '20', 6, '20') && !$overlap('2.4', 1, '20', 3, '20', 10),
        'Channels 1 and 6 do not overlap, and a faint neighbour is not counted.');
    $assert((bool) $overlap('5', 36, '80', 44, '20') && !$overlap('5', 36, '80', 52, '20') && !$overlap('5', 36, '80', 36, '80'),
        'An 80 MHz block on 36 overlaps 44 but not 52; the same channel is co-channel, not overlap.');

    echo "Wi-Fi floor and RF checks passed ($checks checks).\n";
})();
