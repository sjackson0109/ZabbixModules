<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiHistory;
use Modules\WifiExplorer\Services\WifiLimits;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/** Snapshot history for the timeline: per host and key, [clock, value] newest first, like the API. */
final class FixtureHistory implements WifiHistory {
    public array $rows = [];
    public array $requests = [];
    public function window(string $hostid, string $key, int $from, int $till, int $limit, int $maxBytes): array {
        $this->requests[] = [$hostid, $key, $from, $till, $limit, $maxBytes];
        $rows = array_values(array_filter($this->rows[$hostid][$key] ?? [], static fn($r) => $r['clock'] >= $from
            && $r['clock'] <= $till));
        usort($rows, static fn($a, $b) => $b['clock'] <=> $a['clock']);
        return array_slice($rows, 0, $limit);
    }
}

/** Phase F: current clients, search under the privacy policy, one client's trace and its sampled timeline. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $build = static function (array $more, ?WifiHistory $history = null, ?FixtureGateway $gateway = null): array {
        return (new WifiService($gateway ?? WifiLab::gateway(), WifiLab::now(), WifiLab::config(), false, $history))
            ->build(WifiScope::create('lab-west', '', ['view'=>'clients'] + $more));
    };

    $model = $build([]);
    $clients = $model['clients'];
    $assert($clients['total'] === 10 && $clients['matched'] === 10, 'Ten current clients are listed.');
    $assert($clients['sources'][0]['policy'] === 'partial', 'The lab template uses partial identifiers.');
    $assert(!array_filter($clients['clients'], static fn($c) => $c['ip_address'] !== null || $c['name'] !== null
        || !preg_match('/:xx:xx:xx$/', (string) $c['mac_address'])), 'Partial identifiers: masked MAC, no IP, no name.');
    $one = array_column($clients['clients'], null, 'client_uid')['client-2b4dbaae341708bc28d2d519'];
    $assert($one['ap_uid'] === WifiLab::apUid(2) && $one['radio_basis'] === 'bssid' && $one['radio_uid'] !== null,
        'The client\'s AP is matched by address and its radio by exact BSSID.');
    $assert($build(['q'=>'lab-ap-05'])['clients']['matched'] === 3, 'Search by AP name.');
    $assert($build(['q'=>'00:00:5e:00:53:01'])['clients']['matched'] === 0,
        'A full MAC address cannot be found when only the prefix is stored.');
    $assert($build(['q'=>'client-2b4d'])['clients']['matched'] === 1, 'Search by the opaque client ID.');

    // Stale client data: nobody is "connected now".
    $stale = WifiLab::gateway();
    foreach ($stale->itemRows as $item) {
        if ($item['hostid'] === '10' && in_array($item['key_'], ['we.client.snapshot', 'we.client.attempt'], true)) {
            $envelope = json_decode($stale->values[$item['itemid']][0]['value'], true);
            $envelope['observed_at'] = $envelope['attempted_at'] = '2026-10-12T09:00:00Z';
            $stale->values[$item['itemid']] = [['value'=>json_encode($envelope)]];
        }
    }
    $assert($build([], null, $stale)['clients']['total'] === 0, 'A stale client list is not shown as current.');

    // The timeline: four samples, the client moves AP, disappears, returns.
    $target = 'client-2b4dbaae341708bc28d2d519';
    $base = WifiLab::envelope('we.raw.aruba.client', 'aruba-instant-vc.snmprec');
    $history = new FixtureHistory();
    $sample = static function (int $minutesAgo, ?string $ap, ?string $bssid) use ($base, $target): array {
        $time = WifiLab::now() - $minutesAgo * 60;
        $envelope = $base;
        $envelope['observed_at'] = $envelope['attempted_at'] = gmdate('Y-m-d\TH:i:s\Z', $time);
        $envelope['data'] = array_values(array_filter(array_map(static function ($row) use ($target, $ap, $bssid) {
            if ($row['client_uid'] !== $target) {
                return $row;
            }
            return $ap === null ? null : ['ap_uid'=>$ap, 'bssid'=>$bssid] + $row;
        }, $envelope['data'])));
        return ['clock'=>$time, 'value'=>json_encode($envelope)];
    };
    $history->rows['10']['we.client.snapshot'] = [
        $sample(40, WifiLab::apUid(1), '00:00:5e:00:53:84'), $sample(30, WifiLab::apUid(2), '00:00:5e:00:53:88'),
        $sample(20, null, null), $sample(10, WifiLab::apUid(2), '00:00:5e:00:53:89'),
        $sample(0, WifiLab::apUid(2), '00:00:5e:00:53:88'), ['clock'=>WifiLab::now() - 5 * 60, 'value'=>'not json'],
        $sample(400, WifiLab::apUid(5), '00:00:5e:00:53:94')];
    $timeline = $build(['client'=>$target], $history)['clients']['timeline'];
    $assert($timeline['available'] && count($timeline['samples']) === 5,
        'Five valid samples in the window; an invalid one is skipped and an older one is outside the window.');
    $assert(array_column($timeline['changes'], 'type') === ['ap_changed', 'left', 'appeared', 'bssid_changed'],
        'Changes between samples, in order.');
    $assert($timeline['changes'][0]['from_ap'] === WifiLab::apUid(1) && $timeline['changes'][0]['to_ap'] === WifiLab::apUid(2)
        && $timeline['changes'][0]['kind'] === 'inferred', 'An AP change is inferred between two sample times.');
    $assert($history->requests[0][0] === '10' && $history->requests[0][1] === 'we.client.snapshot'
        && $history->requests[0][4] === WifiLimits::CLIENT_HISTORY_SAMPLES + 1,
        'History is read from the client\'s own cluster, bounded by sample count.');
    $assert($history->requests[0][5] === WifiLimits::CLIENT_HISTORY_BYTES, 'The reader is told the byte bound, so it stops there.');
    $assert($clients['sources'][0]['unkeyed'] === true, 'Client IDs without WE.CLIENT.KEY are reported as not keyed.');

    $missing = $build(['client'=>'client-000000000000000000000000'], $history)['clients'];
    $assert($missing['selection_missing'] && $missing['timeline'] === null, 'An unknown client selects nothing.');
    $assert($build(['client'=>$target])['clients']['timeline']['reason'] === 'history_unavailable',
        'Without a history reader the timeline says so.');
    $assert(WifiScope::create('', '', ['client'=>'00:00:5e:00:53:01'])->client === '',
        'A MAC address is never accepted as a client selection.');

    echo "Wi-Fi client checks passed ({$checks} checks).\n";
})();
