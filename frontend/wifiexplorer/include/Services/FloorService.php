<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Floor plans: configured AP positions with selectable overlays (requirements section 7).
 *
 * Every overlay says what kind of evidence it draws: positions are configured, AP values are observed, and the
 * shaded field between APs is interpolated from those observed values (inverse-distance weighting) and drawn only
 * near an AP. It is not a predictive RF survey and is never labelled as one.
 */
final class FloorService {
    public const OVERLAYS = ['status', 'band', 'channel', 'utilisation', 'clients', 'neighbours', 'retries'];
    /** Interpolation grid columns, and the reach of an AP's value as a fraction of the plan width. */
    private const GRID = 40;
    private const REACH = 0.18;
    private const DEFAULT_ASPECT = 0.6;

    /**
     * @param array  $config  visible configuration (WifiConfig::visible)
     * @param array  $aps     ap_uid => AP
     * @param array  $clients ap_uid => current client count (observed)
     * @param array  $rf      RfService result
     */
    public function build(array $config, array $aps, array $clients, array $rf, string $floorId, string $overlay,
            string $band): array {
        $floors = $config['floors'];
        usort($floors, static fn($a, $b) => [$a['site'], $a['building'], $a['order'], $a['name']]
            <=> [$b['site'], $b['building'], $b['order'], $b['name']]);
        $placed = [];
        foreach ($config['placements'] as $apUid => $place) {
            if (isset($aps[$apUid])) {
                $placed[$place['floor_id']][$apUid] = $place;
            }
        }
        foreach ($floors as &$floor) {
            $floor['ap_count'] = count($placed[$floor['floor_id']] ?? []);
        }
        unset($floor);
        $unplaced = array_values(array_filter(array_keys($aps), static fn($uid) => !isset($config['placements'][$uid])));
        $selected = null;
        foreach ($floors as $floor) {
            if ($floor['floor_id'] === $floorId) {
                $selected = $floor;
            }
        }
        $result = ['floors'=>$floors, 'unplaced'=>$unplaced, 'selected_floor'=>null,
            'floor_missing'=>$floorId !== '' && $selected === null, 'overlays'=>self::OVERLAYS];
        if ($selected === null) {
            return $result;
        }
        $overlay = in_array($overlay, self::OVERLAYS, true) ? $overlay : 'status';
        $band = in_array($band, ['2.4', '5', '6'], true) ? $band : '';
        $aspect = $selected['aspect'] ?? self::DEFAULT_ASPECT;
        $neighbourCounts = [];
        foreach ($rf['observers'] as $observer) {
            if ($observer['ap_uid'] !== null && $observer['freshness'] === 'current') {
                $neighbourCounts[$observer['ap_uid']] = $observer['counts'];
            }
        }
        $markers = [];
        foreach ($placed[$selected['floor_id']] ?? [] as $apUid => $place) {
            $ap = $aps[$apUid];
            $radios = array_values(array_filter($ap['radios'], static fn($r) => $band === '' || $r['band'] === $band));
            $util = array_filter(array_map(static fn($r) => $r['status'] === 'up' && $r['state_freshness'] === 'current'
                ? $r['utilisation_percent'] : null, $radios), static fn($v) => $v !== null);
            $counts = $neighbourCounts[$apUid] ?? null;
            $markers[] = ['ap_uid'=>$apUid, 'name'=>$ap['name'], 'status'=>$ap['status'], 'degraded'=>$ap['degraded'],
                'x'=>$place['x'], 'y'=>$place['y'] * $aspect,
                'radios'=>array_map(static fn($r) => ['radio_uid'=>$r['radio_uid'], 'band'=>$r['band'],
                    'channel'=>$r['status'] === 'up' && $r['state_freshness'] === 'current' ? $r['channel'] : null,
                    'status'=>$r['status'], 'utilisation_percent'=>$r['utilisation_percent']], $radios),
                'utilisation'=>$util ? max($util) : null,
                'clients'=>$clients[$apUid] ?? null,
                'neighbours'=>$counts === null ? null : array_sum($counts) - ($counts['managed'] ?? 0),
                'flagged'=>$counts['flagged'] ?? null];
        }
        $metric = ['utilisation'=>'utilisation', 'clients'=>'clients', 'neighbours'=>'neighbours'][$overlay] ?? null;
        $result['selected_floor'] = $selected + ['aspect_used'=>$aspect, 'markers'=>$markers, 'overlay'=>$overlay,
            'band'=>$band, 'legend'=>$this->legend($overlay),
            'field'=>$metric !== null ? $this->field($markers, $metric, $aspect) : null,
            'reuse'=>$overlay === 'channel' ? $this->reuse($markers, $rf, $aps) : []];
        return $result;
    }

    /** What the overlay draws and what kind of evidence it is. */
    private function legend(string $overlay): array {
        $kinds = ['status'=>['observed', _('AP state from the latest current observation.')],
            'band'=>['observed', _('Bands of each AP\'s radios as observed; an unproven band is shown as unknown.')],
            'channel'=>['observed', _('Current channels. A solid line joins two APs on one channel where one hears the other (observed RF evidence); a dashed line is channel reuse with no RF evidence, which is not interference by itself.')],
            'utilisation'=>['interpolated', _('Observed channel utilisation at each AP; the shading between APs is interpolated from those values and shows no measurement of its own. It is not a predictive RF survey.')],
            'clients'=>['interpolated', _('Observed client count at each AP; the shading between APs is interpolated from those counts.')],
            'neighbours'=>['interpolated', _('Networks outside the visible inventory that each AP hears (observed); the shading between APs is interpolated from those counts.')],
            'retries'=>['not_collected', _('Retry and error rates are not exposed by this source (AI-AP-MIB on Instant), so nothing is drawn.')]];
        return ['kind'=>$kinds[$overlay][0], 'text'=>$kinds[$overlay][1], 'positions'=>'configured'];
    }

    /**
     * Inverse-distance-weighted field from the observed AP values, only within REACH of an AP.
     * @return array{columns: int, rows: int, cell: float, max: float, cells: array}|null
     */
    private function field(array $markers, string $metric, float $aspect): ?array {
        $points = array_values(array_filter($markers, static fn($m) => $m[$metric] !== null));
        if (!$points) {
            return null;
        }
        $cell = 1 / self::GRID;
        $rows = max(1, (int) ceil($aspect / $cell));
        $max = max(1, max(array_column($points, $metric)));
        $cells = [];
        for ($r = 0; $r < $rows; ++$r) {
            for ($c = 0; $c < self::GRID; ++$c) {
                $x = ($c + 0.5) * $cell;
                $y = ($r + 0.5) * $cell;
                $sum = 0.0;
                $weights = 0.0;
                $near = false;
                foreach ($points as $p) {
                    $d2 = ($p['x'] - $x) ** 2 + ($p['y'] - $y) ** 2;
                    $near = $near || $d2 <= self::REACH ** 2;
                    $w = 1 / max($d2, 1e-6);
                    $sum += $w * $p[$metric];
                    $weights += $w;
                }
                if ($near) {
                    $cells[] = [$c, $r, round($sum / $weights / $max, 3)];
                }
            }
        }
        return ['columns'=>self::GRID, 'rows'=>$rows, 'cell'=>$cell, 'max'=>$max, 'cells'=>$cells];
    }

    /** Pairs of placed APs on one channel, marked heard (RF evidence from either side) or reuse only. */
    private function reuse(array $markers, array $rf, array $aps): array {
        $hears = [];
        foreach ($rf['neighbours'] as $row) {
            if ($row['class'] !== 'managed' || $row['managed_ap_uid'] === null) {
                continue;
            }
            foreach ($row['observers'] as $o) {
                if ($o['ap_uid'] !== null && $o['freshness'] === 'current') {
                    $hears[$o['ap_uid']][$row['managed_ap_uid']] = true;
                }
            }
        }
        $pairs = [];
        $count = count($markers);
        for ($i = 0; $i < $count; ++$i) {
            for ($j = $i + 1; $j < $count; ++$j) {
                $a = $markers[$i];
                $b = $markers[$j];
                $shared = array_intersect(array_filter(array_column($a['radios'], 'channel')),
                    array_filter(array_column($b['radios'], 'channel')));
                if (!$shared) {
                    continue;
                }
                $pairs[] = ['a'=>$a['ap_uid'], 'b'=>$b['ap_uid'], 'channels'=>array_values(array_unique($shared)),
                    'heard'=>isset($hears[$a['ap_uid']][$b['ap_uid']]) || isset($hears[$b['ap_uid']][$a['ap_uid']])];
            }
        }
        return $pairs;
    }
}
