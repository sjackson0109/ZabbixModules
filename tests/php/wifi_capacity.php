<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\CapacityService;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;
use Modules\WifiExplorer\Services\WifiTrends;

/** Hourly trend rows per host and key, like the API: [hostid, key, clock, avg, max]. */
final class FixtureTrends implements WifiTrends {
    public array $rows = [];
    public array $requests = [];
    public function trends(array $hostids, array $keys, int $from, int $till, int $limit): array {
        $this->requests[] = [$hostids, $keys, $from, $till, $limit];
        return array_slice(array_values(array_filter($this->rows, static fn($r) => in_array($r[0], $hostids, true)
            && in_array($r[1], $keys, true) && $r[2] >= $from && $r[2] <= $till)), 0, $limit + 1);
    }
}

/** Phase G: long-term capacity from hourly trends, gaps kept as gaps. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = WifiLab::now();
    $hour = intdiv($now, 3600) * 3600;
    $trends = new FixtureTrends();
    // 40 days of the lab cluster: 10 clients at night, 30 by day, one more client per day in the last week;
    // a 48-hour collection gap ten days ago; 5 GHz peaks of 85% at noon.
    for ($h = 1; $h <= 40 * 24; ++$h) {
        $clock = $hour - $h * 3600;
        if ($h > 240 && $h <= 288) {
            continue;
        }
        $day = (int) gmdate('G', $clock) >= 9 && (int) gmdate('G', $clock) < 17;
        $clients = ($day ? 30.0 : 10.0) + ($h <= 168 ? 1.0 : 0.0);
        $trends->rows[] = ['10', 'we.capacity.clients', $clock, $clients, $clients + 2];
        $trends->rows[] = ['10', 'we.capacity.clients.ap_max', $clock, 4.0, $day ? 9.0 : 3.0];
        $trends->rows[] = ['10', 'we.capacity.aps.up', $clock, 5.0, 5.0];
        $trends->rows[] = ['10', 'we.capacity.aps.down', $clock, 1.0, 1.0];
        $trends->rows[] = ['10', 'we.capacity.radios.up[5]', $clock, 5.0, 5.0];
        $trends->rows[] = ['10', 'we.capacity.utilisation.avg[5]', $clock, 40.0, 50.0];
        $trends->rows[] = ['10', 'we.capacity.utilisation.max[5]', $clock, 60.0, (int) gmdate('G', $clock) === 12 ? 85.0 : 60.0];
    }
    // A cluster the viewer cannot read: its trends must never count.
    $trends->rows[] = ['99', 'we.capacity.clients', $hour - 3600, 5000.0, 5000.0];
    $build = static function (string $range, ?WifiTrends $reader = null) use ($trends, $now): array {
        return (new WifiService(WifiLab::gateway(), $now, WifiLab::config(), false, null, $reader ?? $trends))
            ->build(WifiScope::create('lab-west', '', ['view'=>'capacity', 'range'=>$range]));
    };

    $month = $build('month')['capacity'];
    $assert($month['available'] && $month['range'] === 'month' && count($month['periods']) >= 30, 'Thirty daily periods.');
    $assert($month['hours_with_data'] === 720 - 48 && $month['hours'] === 720, 'The 48-hour gap is counted as hours without data.');
    $gap = array_values(array_filter($month['periods'], static fn($p) => $p['hours_with_data'] === 0));
    $assert($gap !== [] && $gap[0]['clients_avg'] === null && $gap[0]['clients_ap_max'] === null,
        'A day without observations has no value, never zero.');
    $last = $month['periods'][count($month['periods']) - 2];   // yesterday: a whole day
    $assert($last['clients_peak_hour'] === 31.0 && $last['clients_ap_max'] === 9.0 && $last['aps_down_max'] === 1.0,
        'The busiest hour, the busiest AP and the APs down are read per day.');
    $assert($last['utilisation']['5']['max'] === 85.0 && $last['utilisation']['5']['avg'] === 40.0
        && $last['utilisation']['2.4']['max'] === null, 'Utilisation per band; a band without data stays unknown.');
    $assert(abs($month['growth']['percent'] - 1 / (10 + 20 * 8 / 24) * 100) < 0.01,
        'Growth: the last seven days against the seven before.');
    $assert(!array_filter($month['clusters'], static fn($c) => $c['hostid'] === '99') && $last['clients_peak_hour'] < 5000,
        'Trends of a cluster the viewer cannot read never count.');
    $assert($trends->requests[0][0] === ['10', '20'] || $trends->requests[0][0] === ['20', '10'],
        'Trends are requested only for the visible owners.');

    $day = $build('day')['capacity'];
    $assert(count($day['periods']) === 24 && $day['periods'][23]['start'] === $hour - 3600,
        'The day view has one period per hour, up to the last full hour.');
    $year = $build('year')['capacity'];
    $keys = end($trends->requests)[1];
    $assert($year['available'] && count($year['periods']) >= 12 && !in_array('we.capacity.utilisation.avg[5]', $keys, true)
        && in_array('we.capacity.utilisation.max[5]', $keys, true), 'The year view is monthly and reads peaks only.');
    $assert($year['growth'] !== null, 'Growth is shown in the year view too.');

    $assert($build('month', new FixtureTrends())['capacity']['reason'] === 'no_trends', 'No trends yet is said so.');
    $none = (new WifiService(WifiLab::gateway(), $now, WifiLab::config()))
        ->build(WifiScope::create('lab-west', '', ['view'=>'capacity']))['capacity'];
    $assert($none['reason'] === 'trends_unavailable', 'Without a trend reader the view says so.');
    $assert($build('month')['capacity'] !== null && (new WifiService(WifiLab::gateway(), $now, WifiLab::config(), false, null,
        $trends))->build(WifiScope::create('lab-west'))['capacity'] === null, 'Only the capacity view reads trends.');
    $assert(WifiScope::create('', '', ['range'=>'decade'])->range === 'month', 'An unknown range falls back to a month.');
    $assert(count(CapacityService::keys()) === 13 && count(CapacityService::keys(true)) === 7, 'Thirteen capacity keys.');

    echo "Wi-Fi capacity checks passed ({$checks} checks).\n";
})();
