<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Long-term capacity (requirements section 16): the site's clients, APs and channel utilisation over the last day,
 * month or year, from Zabbix's hourly trends of the templates' numeric capacity items (one set per cluster).
 *
 * Only complete observations ever produce a capacity value, so an hour with no trend row is a gap, never a zero.
 * Site values add the clusters that reported in that hour, and each period says how many of its hours had data.
 * A peak is the busiest hour's average, not an instantaneous maximum; the utilisation peak is the highest sample
 * any radio reported. Client count alone is not presented as capacity: utilisation, the busiest AP and the APs
 * down sit beside it.
 */
final class CapacityService {
    public const RANGES = ['day'=>[86400, 3600], 'month'=>[2592000, 86400], 'year'=>[31536000, 0]];
    public const BANDS = ['2.4', '5', '6'];
    private const HOUR = 3600;

    /**
     * The capacity keys the templates produce. The year view leaves out radios up and average utilisation, which
     * keeps a year of hourly rows within the read budget for a site of several clusters.
     * @return string[]
     */
    public static function keys(bool $year = false): array {
        $keys = ['we.capacity.clients', 'we.capacity.clients.ap_max', 'we.capacity.aps.up', 'we.capacity.aps.down'];
        foreach (self::BANDS as $band) {
            if (!$year) {
                $keys[] = 'we.capacity.radios.up['.$band.']';
                $keys[] = 'we.capacity.utilisation.avg['.$band.']';
            }
            $keys[] = 'we.capacity.utilisation.max['.$band.']';
        }
        return $keys;
    }

    private ?WifiTrends $trends;
    private int $now;

    public function __construct(?WifiTrends $trends, int $now) {
        $this->trends = $trends;
        $this->now = $now;
    }

    /** @param array $owners hostid => owner; only clusters (owners with a device dataset) carry capacity items */
    public function build(array $owners, string $range): array {
        [$span, $step] = self::RANGES[$range] ?? self::RANGES['month'];
        $till = intdiv($this->now, self::HOUR) * self::HOUR - 1;
        $from = $till + 1 - $span;
        $base = ['available'=>false, 'reason'=>null, 'range'=>$range, 'from'=>$from, 'till'=>$till, 'clusters'=>[],
            'periods'=>[], 'growth'=>null, 'bands'=>[], 'hours'=>0, 'hours_with_data'=>0, 'kind'=>'trend'];
        // Clusters carry the capacity items; a per-AP RF host simply has none.
        $hostids = array_map('strval', array_keys($owners));
        if ($this->trends === null) {
            return ['reason'=>'trends_unavailable'] + $base;
        }
        if (!$hostids) {
            return ['reason'=>'no_clusters'] + $base;
        }
        $rows = $this->trends->trends($hostids, self::keys($range === 'year'), $from, $till, WifiLimits::TREND_ROWS);
        if (count($rows) > WifiLimits::TREND_ROWS) {
            return ['reason'=>'too_many_rows'] + $base;
        }
        if (!$rows) {
            return ['reason'=>'no_trends'] + $base;
        }

        // hour => key => hostid => trend row
        $hours = [];
        foreach ($rows as [$hostid, $key, $clock, $avg, $max]) {
            if (!isset($owners[$hostid]) || $clock < $from || $clock > $till) {
                continue;
            }
            $hours[intdiv($clock, self::HOUR) * self::HOUR][$key][$hostid] = ['avg'=>$avg, 'max'=>$max];
        }
        unset($rows);
        ksort($hours);
        $site = [];
        foreach ($hours as $hour => $byKey) {
            $site[$hour] = $this->siteHour($byKey);
        }

        $periods = [];
        foreach ($site as $hour => $values) {
            $periods[$this->bucket($hour, $step)][$hour] = $values;
        }
        $result = [];
        foreach ($this->buckets($from, $till, $step) as [$start, $length]) {
            $result[] = $this->period($start, $length, $periods[$start] ?? []);
        }
        $clusters = [];
        foreach ($hostids as $hostid) {
            $clusters[] = $this->cluster($hostid, $owners[$hostid], $hours);
        }
        usort($clusters, static fn($a, $b) => strnatcasecmp($a['name'], $b['name']));
        $latest = end($site) ?: [];
        return ['available'=>true, 'periods'=>$result, 'clusters'=>$clusters, 'growth'=>$this->growth($site),
            'bands'=>array_map(static fn($band) => ['band'=>$band, 'radios_up'=>$latest['radios_up'][$band] ?? null],
                self::BANDS),
            'hours'=>intdiv($span, self::HOUR), 'hours_with_data'=>count($site)] + $base;
    }

    /** The site in one hour: the clusters that reported, added up (utilisation weighted by radios up). */
    private function siteHour(array $byKey): array {
        $sum = static fn(string $key, string $field) => isset($byKey[$key])
            ? array_sum(array_column($byKey[$key], $field)) : null;
        $max = static fn(string $key) => isset($byKey[$key]) ? max(array_column($byKey[$key], 'max')) : null;
        $values = ['clients'=>$sum('we.capacity.clients', 'avg'), 'clients_ap_max'=>$max('we.capacity.clients.ap_max'),
            'aps_up'=>$sum('we.capacity.aps.up', 'avg'), 'aps_down'=>$sum('we.capacity.aps.down', 'max'),
            'clusters'=>count($byKey['we.capacity.clients'] ?? []), 'radios_up'=>[], 'utilisation_avg'=>[],
            'utilisation_max'=>[]];
        foreach (self::BANDS as $band) {
            $values['radios_up'][$band] = $sum('we.capacity.radios.up['.$band.']', 'avg');
            $values['utilisation_max'][$band] = $max('we.capacity.utilisation.max['.$band.']');
            $weighted = 0.0;
            $weights = 0.0;
            foreach ($byKey['we.capacity.utilisation.avg['.$band.']'] ?? [] as $hostid => $row) {
                $weight = $byKey['we.capacity.radios.up['.$band.']'][$hostid]['avg'] ?? 1.0;
                $weighted += $row['avg'] * max($weight, 1.0);
                $weights += max($weight, 1.0);
            }
            $values['utilisation_avg'][$band] = $weights > 0 ? $weighted / $weights : null;
        }
        return $values;
    }

    private function period(int $start, int $length, array $hours): array {
        $clients = array_values(array_filter(array_column($hours, 'clients'), static fn($v) => $v !== null));
        $row = ['start'=>$start, 'length_s'=>$length, 'hours'=>intdiv($length, self::HOUR), 'hours_with_data'=>count($hours),
            'clients_avg'=>$clients ? array_sum($clients) / count($clients) : null,
            'clients_peak_hour'=>$clients ? max($clients) : null, 'clients_p95_hour'=>self::percentile($clients, 95),
            'clients_ap_max'=>self::maxOf(array_column($hours, 'clients_ap_max')),
            'aps_up_avg'=>self::meanOf(array_column($hours, 'aps_up')),
            'aps_down_max'=>self::maxOf(array_column($hours, 'aps_down')), 'utilisation'=>[]];
        foreach (self::BANDS as $band) {
            $averages = array_map(static fn($h) => $h['utilisation_avg'][$band], $hours);
            $peaks = array_map(static fn($h) => $h['utilisation_max'][$band], $hours);
            $row['utilisation'][$band] = ['avg'=>self::meanOf($averages), 'p95_hour'=>self::percentile(
                array_values(array_filter($averages, static fn($v) => $v !== null)), 95), 'max'=>self::maxOf($peaks)];
        }
        return $row;
    }

    private function cluster(string $hostid, array $owner, array $hours): array {
        $clients = [];
        $peaks = array_fill_keys(self::BANDS, null);
        foreach ($hours as $byKey) {
            if (isset($byKey['we.capacity.clients'][$hostid])) {
                $clients[] = $byKey['we.capacity.clients'][$hostid]['avg'];
            }
            foreach (self::BANDS as $band) {
                $row = $byKey['we.capacity.utilisation.max['.$band.']'][$hostid] ?? null;
                if ($row !== null && ($peaks[$band] === null || $row['max'] > $peaks[$band])) {
                    $peaks[$band] = $row['max'];
                }
            }
        }
        return ['hostid'=>$hostid, 'name'=>$owner['name'], 'site'=>$owner['site'] ?? null, 'hours_with_data'=>count($clients),
            'clients_avg'=>$clients ? array_sum($clients) / count($clients) : null,
            'clients_peak_hour'=>$clients ? max($clients) : null, 'utilisation_max'=>$peaks];
    }

    /**
     * Client growth: the last seven days' average against the seven before, only when both weeks have data for at
     * least half their hours, so a collection gap is not read as a change in demand.
     */
    private function growth(array $site): ?array {
        $end = intdiv($this->now, self::HOUR) * self::HOUR;
        $week = 7 * 86400;
        $mean = static function (int $from, int $to) use ($site): array {
            $values = [];
            foreach ($site as $hour => $row) {
                if ($hour >= $from && $hour < $to && $row['clients'] !== null) {
                    $values[] = $row['clients'];
                }
            }
            return [$values ? array_sum($values) / count($values) : null, count($values)];
        };
        [$recent, $recentHours] = $mean($end - $week, $end);
        [$before, $beforeHours] = $mean($end - 2 * $week, $end - $week);
        if ($recent === null || $before === null || $recentHours < 84 || $beforeHours < 84) {
            return null;
        }
        return ['recent_avg'=>$recent, 'previous_avg'=>$before,
            'percent'=>$before > 0 ? ($recent - $before) / $before * 100 : null];
    }

    /** @return array<int, array{0: int, 1: int}> start and length of every period in the range, oldest first */
    private function buckets(int $from, int $till, int $step): array {
        $buckets = [];
        if ($step > 0) {
            for ($start = intdiv($from, $step) * $step; $start <= $till; $start += $step) {
                $buckets[] = [$start, $step];
            }
            return $buckets;
        }
        // Calendar months (UTC).
        $start = gmmktime(0, 0, 0, (int) gmdate('n', $from), 1, (int) gmdate('Y', $from));
        while ($start <= $till) {
            $next = gmmktime(0, 0, 0, (int) gmdate('n', $start) + 1, 1, (int) gmdate('Y', $start));
            $buckets[] = [$start, $next - $start];
            $start = $next;
        }
        return $buckets;
    }

    private function bucket(int $hour, int $step): int {
        return $step > 0 ? intdiv($hour, $step) * $step : gmmktime(0, 0, 0, (int) gmdate('n', $hour), 1,
            (int) gmdate('Y', $hour));
    }

    private static function meanOf(array $values): ?float {
        $values = array_filter($values, static fn($v) => $v !== null);
        return $values ? array_sum($values) / count($values) : null;
    }

    private static function maxOf(array $values) {
        $values = array_filter($values, static fn($v) => $v !== null);
        return $values ? max($values) : null;
    }

    /** Nearest-rank percentile of hourly values, or null without data. */
    private static function percentile(array $values, int $p): ?float {
        if (!$values) {
            return null;
        }
        sort($values);
        return (float) $values[max(0, (int) ceil($p / 100 * count($values)) - 1)];
    }
}
