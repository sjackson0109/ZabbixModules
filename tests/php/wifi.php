<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/wifiexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';
require_once __DIR__.'/services.php';

use Modules\WifiExplorer\Services\WifiDatasetReader;
use Modules\WifiExplorer\Services\WifiEnvelopeValidator;
use Modules\WifiExplorer\Services\WifiFindingList;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/**
 * Wi-Fi Explorer's reader and model, fed by the real template normalisers run over the synthetic Aruba Instant walks:
 * permission filtering, freshness, the member-AP case, duplicate owners and the trust boundary.
 */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = strtotime('2026-10-12T12:00:00Z');
    $root = dirname(__DIR__, 2);
    $walks = $root.'/tests/fixtures/wifi/walks/';
    $raw = ['device'=>'we.raw.aruba.system', 'ap_inventory'=>'we.raw.aruba.ap.inventory',
        'ap_state'=>'we.raw.aruba.ap.state', 'radio_inventory'=>'we.raw.aruba.radio.inventory',
        'radio_state'=>'we.raw.aruba.radio.state', 'ssid'=>'we.raw.aruba.ssid', 'client'=>'we.raw.aruba.client',
        'rf_neighbour'=>'we.raw.aruba.rf.neighbour'];
    $snapshot = array_flip(WifiDatasetReader::KEYS);
    $attemptKey = array_flip(WifiDatasetReader::ATTEMPTS);
    // The normaliser stamps the current time; the fixtures pin it so freshness is deterministic.
    $normalise = static function (string $dataset, string $walk, string $time) use ($root, $walks, $raw): array {
        $out = shell_exec('node '.escapeshellarg($root.'/tests/js/run_normaliser.cjs').' '.escapeshellarg($raw[$dataset])
            .' '.escapeshellarg($walks.$walk));
        $envelope = json_decode((string) $out, true, 512, JSON_THROW_ON_ERROR);
        $envelope['attempted_at'] = $time;
        if ($envelope['observed_at'] !== null) {
            $envelope['observed_at'] = $time;
        }
        return $envelope;
    };
    $host = static fn(string $id, string $name, string $site, int $available = 1): array => ['hostid'=>$id,
        'host'=>$name, 'name'=>$name, 'tags'=>$site === '' ? [] : [['tag'=>'site', 'value'=>$site]],
        'interfaces'=>[['type'=>2, 'useip'=>1, 'ip'=>'192.0.2.'.(int) $id, 'available'=>$available]]];
    $feed = static function (FixtureGateway $gateway, string $hostid, string $walk, string $time,
            array $only = []) use ($normalise, $snapshot, $attemptKey): array {
        $out = [];
        foreach (array_keys($snapshot) as $dataset) {
            if ($only && !in_array($dataset, $only, true)) {
                continue;
            }
            $envelope = $normalise($dataset, $walk, $time);
            $out[$dataset] = $envelope;
            $gateway->add($hostid, $attemptKey[$dataset], [$envelope]);
            if ($envelope['status'] === 'ok' && $envelope['complete']) {
                $gateway->add($hostid, $snapshot[$dataset], [$envelope]);
            }
        }
        return $out;
    };

    // The trust boundary: real normaliser output is accepted; Network Explorer envelopes and bad rows are not.
    $validator = new WifiEnvelopeValidator();
    $fresh = '2026-10-12T11:58:00Z';
    $vcInventory = $normalise('ap_inventory', 'aruba-instant-vc.snmprec', $fresh);
    $assert(count($validator->decode(json_encode($vcInventory), 'ap_inventory')['data']) === 6,
        'The synthetic VC lists six APs.');
    $reject = static function (array $envelope, string $dataset, string $why) use ($validator, $assert): void {
        try {
            $validator->decode(json_encode($envelope), $dataset);
            $assert(false, $why);
        }
        catch (InvalidArgumentException $e) {
            $assert(true, $why);
        }
    };
    $reject(['schema_version'=>'1.1'] + $vcInventory, 'ap_inventory', 'A Network Explorer schema is not a Wi-Fi envelope.');
    $reject($vcInventory, 'ap_state', 'An envelope for another dataset is rejected.');
    $bad = $vcInventory;
    $bad['data'][0]['ap_uid'] = '00:00:5e:00:53:01';
    $reject($bad, 'ap_inventory', 'A raw MAC address is never accepted as an AP identity.');
    $bad = $vcInventory;
    $bad['data'][1] = $bad['data'][0];
    $reject($bad, 'ap_inventory', 'Duplicate AP identities reject the envelope.');
    $radioState = $normalise('radio_state', 'aruba-instant-vc.snmprec', $fresh);
    $bad = $radioState;
    $bad['data'][0]['band'] = '60';
    $reject($bad, 'radio_state', 'An unknown band is rejected.');
    $bad = $radioState;
    $bad['data'][0]['utilisation_percent'] = 140;
    $reject($bad, 'radio_state', 'Utilisation above 100% is rejected.');
    $assert(WifiScope::create('', 'not-an-ap')->ap === '', 'An invalid AP selection selects nothing.');
    try {
        WifiScope::create("bad\nsite");
        $assert(false, 'A malformed site is rejected.');
    }
    catch (InvalidArgumentException $e) {
        $assert($e->getMessage() === 'invalid_scope_filter', 'A malformed site is rejected.');
    }

    // Host 10: the VC at site lab-west. Host 11: a member AP linked by mistake. Host 12: a second VC host listing the
    // same cluster (duplicate owner). Host 13: a VC the user cannot read, so the gateway never returns it.
    $gateway = new FixtureGateway();
    $gateway->hostRows = [$host('10', 'avc-west', 'lab-west'), $host('11', 'ap-member', 'lab-west'),
        $host('12', 'avc-west-old', 'lab-east')];
    $feed($gateway, '10', 'aruba-instant-vc.snmprec', $fresh);
    $feed($gateway, '11', 'aruba-instant-member.snmprec', $fresh);
    $feed($gateway, '12', 'aruba-instant-vc.snmprec', '2026-10-12T11:30:00Z', ['device', 'ap_inventory']);
    $feed($gateway, '13', 'aruba-instant-vc.snmprec', $fresh, ['device', 'ap_inventory']);
    $service = new WifiService($gateway, $now);

    $all = $service->build(WifiScope::create());
    $assert(count($all['owners']) === 3, 'Every readable Wi-Fi source is an owner; the hidden one is not.');
    $assert(count($all['aps']) === 6 && $all['overview']['aps']['total'] === 6,
        'An AP listed by two owners is counted once.');
    $byName = array_column($all['aps'], null, 'name');
    $assert($byName['lab-ap-01']['owner_hostid'] === '10', 'The owner with the newest inventory owns the AP.');
    $assert(count(array_filter($all['findings'], static fn($f) => $f['rule'] === 'wifi_ap_multiple_owners')) === 6,
        'Each doubly listed AP says so.');
    $assert($byName['lab-ap-03']['status'] === 'down'
        && (bool) array_filter($all['findings'], static fn($f) => $f['rule'] === 'wifi_ap_down'
            && $f['object_id'] === $byName['lab-ap-03']['ap_uid']), 'A down AP is a warning finding.');
    $assert($byName['lab-ap-04']['degraded'], 'An up AP with a down radio is degraded.');
    $assert(count(array_filter($all['findings'], static fn($f) => $f['rule'] === 'wifi_radio_high_utilisation')) === 1,
        'The radio at 82% utilisation is flagged.');
    $assert($all['overview']['bands']['6'] === 1 && $all['overview']['bands']['unknown'] >= 2,
        'A 6 GHz channel is proven; overlapping channel numbers on a tri-radio AP stay unknown.');
    $assert((bool) array_filter($all['findings'], static fn($f) => $f['rule'] === 'wifi_radio_band_unknown'),
        'Unknown bands are reported, not guessed.');
    $assert($byName['lab-ap-06']['radios'] === [], 'An AP without radios reports none.');
    $member = array_values(array_filter($all['findings'], static fn($f) => $f['rule'] === 'wifi_owner_not_controller'));
    $assert(count($member) === 1 && $member[0]['hostid'] === '11', 'A member AP is explained once, not as five failures.');
    $assert(!array_filter($all['findings'], static fn($f) => $f['hostid'] === '11' && $f['rule'] === 'wifi_dataset_failed'),
        'An unsupported member is not a failure.');
    $assert($all['overview']['not_available'] === WifiService::NOT_AVAILABLE, 'Uncollected capabilities are named.');
    foreach ($all['findings'] as $finding) {
        $assert(is_string($finding['id']) && strlen($finding['id']) === 64 && is_array($finding['evidence'])
            && isset($finding['freshness'], $finding['confidence']), 'Every finding carries ID, evidence and freshness.');
    }
    $assert(!in_array('13', array_column($all['owners'], 'hostid'), true)
        && !array_filter($all['quality'], static fn($q) => $q['hostid'] === '13')
        && !array_filter($all['aps'], static fn($ap) => $ap['owner_hostid'] === '13'),
        'Nothing from an unreadable host reaches the payload, even when its items are found.');

    // A site narrows owners; the AP selection resolves only inside the scope.
    $west = $service->build(WifiScope::create('lab-west', $byName['lab-ap-02']['ap_uid']));
    $assert(count($west['owners']) === 2 && $west['selected_ap'] === $byName['lab-ap-02']['ap_uid'],
        'A site keeps its owners and the selection.');
    $assert(!array_filter($west['findings'], static fn($f) => $f['rule'] === 'wifi_ap_multiple_owners'),
        'Duplicates outside the scope are not reported.');
    $east = $service->build(WifiScope::create('lab-east', $byName['lab-ap-02']['ap_uid']));
    $assert(count($east['owners']) === 1 && $east['selected_ap'] === $byName['lab-ap-02']['ap_uid'],
        'The other owner\'s copy can be selected in its own site.');
    $assert($east['aps'][0]['status'] === 'unknown' && $east['aps'][0]['status_reason'] === 'state_not_collected',
        'Inventory without state is unknown, not up.');
    $assert($service->siteOptions() === ['lab-east', 'lab-west'], 'Sites come from readable owners.');
    $empty = $service->build(WifiScope::create('nowhere', $byName['lab-ap-02']['ap_uid']));
    $assert($empty['owners'] === [] && $empty['aps'] === [] && $empty['selection_missing'],
        'An empty scope selects nothing and says so.');

    // Stale state: the last complete observation is kept, but status becomes unknown and the dataset is reported.
    $stale = new FixtureGateway();
    $stale->hostRows = [$host('10', 'avc-west', 'lab-west')];
    $feed($stale, '10', 'aruba-instant-vc.snmprec', $fresh, ['device', 'ap_inventory', 'radio_inventory']);
    $feed($stale, '10', 'aruba-instant-vc.snmprec', '2026-10-12T11:00:00Z', ['ap_state', 'radio_state']);
    $old = (new WifiService($stale, $now))->build(WifiScope::create());
    $assert($old['overview']['aps']['up'] === 0 && $old['overview']['aps']['unknown'] === 6,
        'A stale "up" is never shown as up.');
    $assert(!array_filter($old['findings'], static fn($f) => in_array($f['rule'], ['wifi_ap_down', 'wifi_radio_high_utilisation'], true)),
        'Stale state raises no state findings.');
    $assert(count(array_filter($old['findings'], static fn($f) => $f['rule'] === 'wifi_dataset_stale')) === 2,
        'Each stale dataset is reported.');
    // The Overview shows one row per host for its collection problems, after the device findings.
    $listed = WifiFindingList::overview($old['findings']);
    $groups = array_values(array_filter($listed, static fn($row) => isset($row['group'])));
    $collection = static fn($f) => in_array($f['rule'], ['wifi_dataset_failed', 'wifi_dataset_stale'], true);
    $assert(array_sum(array_map(static fn($row) => isset($row['group']) ? count($row['group']) : 1, $listed))
        === count($old['findings']), 'Grouping keeps every finding.');
    $assert(count($listed) === count($old['findings']) - count(array_filter($old['findings'], $collection))
        + count(array_unique(array_column(array_filter($old['findings'], $collection), 'hostid'))),
        'A host\'s failed and stale datasets share one row.');
    $assert($groups !== [] && !array_filter($groups, static fn($row) => count($row['group']) < 2),
        'A host with several collection problems gets one row; a single one keeps its own row.');
    $ranks = array_map(static fn($row) => ($row['severity'] === 'warning' ? 0 : 3)
        + (in_array($row['object_type'], ['ap', 'radio'], true) ? 0 : ($collection($row) || $row['object_type'] === 'owner' ? 2 : 1)), $listed);
    $sorted = $ranks;
    sort($sorted);
    $assert($ranks === $sorted, 'Warnings first, AP and radio problems before other findings, collection last.');
    $assert($old['overview']['bands']['unknown'] === $old['overview']['radios']['total'],
        'Bands from stale state count as unknown.');

    // An unreachable SNMP interface is reported as such, and a Network Explorer item value is not read as Wi-Fi.
    $down = new FixtureGateway();
    $down->hostRows = [$host('10', 'avc-west', 'lab-west', 2)];
    $feed($down, '10', 'aruba-instant-vc.snmprec', '2026-10-12T11:00:00Z', ['device']);
    $quality = (new WifiService($down, $now))->build(WifiScope::create())['quality'];
    $assert($quality[0]['status'] === 'failed' && in_array('agent_unreachable', $quality[0]['errors'], true),
        'An unreachable controller is a failure, not silence.');
    $foreign = new FixtureGateway();
    $foreign->hostRows = [$host('10', 'avc-west', 'lab-west')];
    $foreign->add('10', 'we.device.snapshot', [['schema_version'=>'1.1', 'dataset'=>'device', 'data'=>[]]]);
    $result = (new WifiService($foreign, $now))->build(WifiScope::create());
    $assert($result['owners'][0]['role'] === 'unknown' && $result['quality'][0]['status'] === 'failed',
        'An unreadable value fails the dataset instead of being trusted.');

    // A receipt (a complete attempt stored without its rows) never stands in for a missing snapshot.
    $receiptOnly = new FixtureGateway();
    $receiptOnly->hostRows = [$host('10', 'avc-west', 'lab-west')];
    $inventory = $normalise('ap_inventory', 'aruba-instant-vc.snmprec', '2026-10-12T11:58:00Z');
    $receiptOnly->add('10', 'we.ap.inventory.attempt', [['data_rows'=>count($inventory['data']), 'data'=>[],
        'data_omitted'=>true] + $inventory]);
    $feed($receiptOnly, '10', 'aruba-instant-vc.snmprec', '2026-10-12T11:58:00Z', ['device', 'ap_state']);
    $result = (new WifiService($receiptOnly, $now))->build(WifiScope::create());
    $inventoryQuality = array_column($result['quality'], null, 'dataset')['ap_inventory'];
    $assert($inventoryQuality['status'] === 'ok' && $inventoryQuality['observed_at'] === null
        && $inventoryQuality['freshness'] === 'unknown', 'A receipt alone says the attempt succeeded, not what was seen.');

    echo "Wi-Fi Explorer checks passed ($checks checks).\n";
})();
