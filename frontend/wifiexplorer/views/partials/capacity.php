<?php
/**
 * Capacity: the site's clients, APs and channel utilisation over the last day, month or year, from Zabbix's hourly
 * trends of each cluster's capacity items. Gaps are shown as gaps, never as zeros.
 *
 * @var array $data
 * @var CDiv $root
 */
$capacity = $data['capacity'];
$ranges = ['day'=>_('Last 24 hours'), 'month'=>_('Last 30 days'), 'year'=>_('Last 12 months')];
$switcher = (new CList())->addClass('zx-tabs')->addClass('zx-tabs-sub')->setAttribute('role', 'navigation')
    ->setAttribute('aria-label', _('Range'));
foreach ($ranges as $key => $name) {
    $item = (new CLink($name, $link(['view'=>'capacity', 'range'=>$key === 'month' ? '' : $key])))->addClass('zx-tab');
    if ($key === $capacity['range']) {
        $item->setAttribute('aria-current', 'page');
    }
    $switcher->addItem($item);
}
$root->addItem($switcher);
$root->addItem($about(_('From the hourly trends of each cluster\'s capacity items; an hour without a complete observation is a gap, not a zero.'),
    _('Only complete observations give a value. "Busiest hour" is the highest hourly average; utilisation peaks are the highest sample any radio reported. The current hour is not in the trends yet.')));

if (!$capacity['available']) {
    $reasons = [
        'trends_unavailable'=>_('Trends cannot be read here.'),
        'no_clusters'=>_('No visible cluster in this scope.'),
        'no_trends'=>_('No capacity trends yet. They need the current "Wi-Fi Explorer - Aruba Instant VC by SNMP" template and build up hour by hour.'),
        'too_many_rows'=>_('Too much trend data for one view. Choose a site or a shorter range.')
    ];
    $root->addItem((new CDiv($reasons[$capacity['reason']] ?? _('Capacity trends are not available.')))->addClass('msg-warning'));
    return;
}

$number = static fn(?float $value, int $decimals = 0): string => $value === null ? '—' : number_format($value, $decimals);
$percent = static fn(?float $value): string => $value === null ? '—' : number_format($value, 0).'%';
$periodName = static function (array $period) use ($capacity): string {
    $format = $capacity['range'] === 'day' ? 'Y-m-d H:i' : ($capacity['range'] === 'month' ? 'Y-m-d' : 'Y-m');
    return gmdate($format, $period['start']).($capacity['range'] === 'day' ? ' UTC' : '');
};

// Summary tiles: the range as a whole.
$periods = $capacity['periods'];
$withData = array_values(array_filter($periods, static fn($p) => $p['hours_with_data'] > 0));
$maxOf = static function (array $values) {
    $values = array_filter($values, static fn($v) => $v !== null);
    return $values ? max($values) : null;
};
$tiles = (new CDiv())->addClass('we-tiles');
// The same accent rule as Overview: a tile is accented only when it shows something to act on.
$tile = static function (string $title, string $value, string $detail, string $class = ''): CDiv {
    $tile = (new CDiv([(new CDiv($title))->addClass('we-tile-title'), (new CDiv($value))->addClass('we-tile-value'),
        (new CDiv($detail))->addClass('we-tile-detail')]))->addClass('we-tile');
    return $class !== '' ? $tile->addClass($class) : $tile;
};
$growth = $capacity['growth'];
$tiles->addItem($tile(_('Clients, busiest hour'), $number($maxOf(array_column($withData, 'clients_peak_hour'))),
    $growth !== null && $growth['percent'] !== null
        ? _s('Last 7 days %1$s on average, %2$s%% against the 7 before', $number($growth['recent_avg'], 1),
            ($growth['percent'] >= 0 ? '+' : '').number_format($growth['percent'], 1))
        : _('Growth needs two weeks with data for at least half their hours.')));
$meanOf = static function (array $values): ?float {
    $values = array_filter($values, static fn($v) => $v !== null);
    return $values ? array_sum($values) / count($values) : null;
};
$clientsMean = $meanOf(array_column($withData, 'clients_avg'));
$apsMean = $meanOf(array_column($withData, 'aps_up_avg'));
$tiles->addItem($tile(_('Most clients on one AP'), $number($maxOf(array_column($withData, 'clients_ap_max'))),
    $clientsMean !== null && $apsMean !== null && $apsMean > 0
        ? _s('Against %1$s per AP up on average across the site', $number($clientsMean / $apsMean, 1))
        : _('The site average per AP is not known.')));
foreach (\Modules\WifiExplorer\Services\CapacityService::BANDS as $band) {
    $peak = $maxOf(array_map(static fn($p) => $p['utilisation'][$band]['max'], $withData));
    if ($peak !== null) {
        $tiles->addItem($tile(_s('%1$s GHz utilisation peak', $band), $percent($peak),
            _s('%1$s radios up in the last full hour', $number(array_column($capacity['bands'], 'radios_up', 'band')[$band] ?? null)),
            $peak >= \Modules\WifiExplorer\Services\WifiLimits::HIGH_UTILISATION ? 'we-tile-warning' : ''));
    }
}
$tiles->addItem($tile(_('Hours with data'), $capacity['hours_with_data'].' / '.$capacity['hours'],
    _('Hours in the range for which at least one cluster reported a complete observation.'),
    $capacity['hours_with_data'] * 2 < $capacity['hours'] ? 'we-tile-warning' : ''));
$root->addItem($tiles);

// Clients per period: the average and the busiest hour, with a value axis, time labels and a hover tooltip per
// period. Gaps break the lines; they are never drawn as zeros.
$plot = ['left'=>44, 'right'=>96, 'top'=>12, 'bottom'=>28, 'width'=>1000, 'height'=>220];
$values = array_merge(array_column($periods, 'clients_peak_hour'), array_column($periods, 'clients_avg'));
$step = static function (float $max): float {
    // A round tick step giving two to five ticks.
    $raw = max(1.0, $max / 4);
    $magnitude = 10 ** floor(log10($raw));
    foreach ([1, 2, 5, 10] as $factor) {
        if ($factor * $magnitude >= $raw) {
            return $factor * $magnitude;
        }
    }
    return 10 * $magnitude;
};
$tick = $step((float) ($maxOf($values) ?? 1));
$top = max($tick, ceil((float) ($maxOf($values) ?? 1) / $tick) * $tick);
$count = max(1, count($periods));
$innerWidth = $plot['width'] - $plot['left'] - $plot['right'];
$innerHeight = $plot['height'] - $plot['top'] - $plot['bottom'];
$fmt = static fn(float $v): string => number_format($v, 1, '.', '');
$x = static fn(int $i): float => $plot['left'] + ($i + 0.5) * $innerWidth / $count;
$y = static fn(float $v): float => $plot['top'] + $innerHeight - $v / $top * $innerHeight;
$svg = (new CTag('svg', true))->addClass('we-capacity-chart')
    ->setAttribute('viewBox', '0 0 '.$plot['width'].' '.$plot['height'])->setAttribute('role', 'img')
    ->setAttribute('aria-label', _('Clients per period: average and busiest hour. The table below lists every value.'));
for ($v = 0.0; $v <= $top + 0.001; $v += $tick) {
    $svg->addItem((new CTag('line', true))->addClass('we-capacity-grid')->setAttribute('x1', $plot['left'])
        ->setAttribute('x2', $plot['width'] - $plot['right'])->setAttribute('y1', $fmt($y($v)))->setAttribute('y2', $fmt($y($v))));
    $svg->addItem((new CTag('text', true, $number($v)))->addClass('we-capacity-axis')->setAttribute('x', $plot['left'] - 6)
        ->setAttribute('y', $fmt($y($v) + 4))->setAttribute('text-anchor', 'end'));
}
$short = static function (array $period) use ($capacity): string {
    return gmdate($capacity['range'] === 'day' ? 'H:i' : ($capacity['range'] === 'month' ? 'd M' : 'M Y'), $period['start']);
};
$every = max(1, (int) ceil($count / 8));
foreach ($periods as $i => $period) {
    if ($i % $every === 0 || $i === $count - 1) {
        $svg->addItem((new CTag('text', true, $short($period)))->addClass('we-capacity-axis')->setAttribute('x', $fmt($x($i)))
            ->setAttribute('y', $plot['height'] - 8)->setAttribute('text-anchor', 'middle'));
    }
}
// In the day view each period is one hour, so its busiest hour is its average: one line, not two on top of each other.
$lines = $capacity['range'] === 'day'
    ? ['clients_avg'=>['we-capacity-avg', _('Hourly average')]]
    : ['clients_peak_hour'=>['we-capacity-peak', _('Busiest hour')], 'clients_avg'=>['we-capacity-avg', _('Average')]];
$ends = [];
foreach ($lines as $field => [$class, $name]) {
    $segment = [];
    $flush = static function () use (&$segment, $svg, $class): void {
        if (count($segment) > 1) {
            $svg->addItem((new CTag('polyline', true))->setAttribute('points', implode(' ', $segment))->addClass($class));
        }
        elseif (count($segment) === 1) {
            [$cx, $cy] = explode(',', $segment[0]);
            $svg->addItem((new CTag('circle', true))->setAttribute('cx', $cx)->setAttribute('cy', $cy)->setAttribute('r', 3)
                ->addClass($class));
        }
        $segment = [];
    };
    foreach ($periods as $i => $period) {
        if ($period[$field] === null) {
            $flush();
            continue;
        }
        $segment[] = $fmt($x($i)).','.$fmt($y((float) $period[$field]));
        $ends[$field] = [$i, (float) $period[$field]];
    }
    $flush();
}
// Direct labels at the right-hand end of each line, nudged apart when the lines meet.
$labelY = [];
foreach ($lines as $field => [$class, $name]) {
    if (isset($ends[$field])) {
        $labelY[$field] = $y($ends[$field][1]) + 4;
    }
}
if (count($labelY) === 2 && abs($labelY['clients_avg'] - $labelY['clients_peak_hour']) < 14) {
    $middle = ($labelY['clients_avg'] + $labelY['clients_peak_hour']) / 2;
    $labelY['clients_peak_hour'] = $middle - 7;
    $labelY['clients_avg'] = $middle + 7;
}
foreach ($labelY as $field => $ly) {
    $svg->addItem((new CTag('text', true, $lines[$field][1]))->addClass('we-capacity-label')
        ->addClass($lines[$field][0].'-label')->setAttribute('x', $plot['width'] - $plot['right'] + 6)
        ->setAttribute('y', $fmt($ly)));
}
// One hover target per period, with its values.
foreach ($periods as $i => $period) {
    $hit = (new CTag('rect', true))->addClass('we-capacity-hit')->setAttribute('x', $fmt($x($i) - $innerWidth / $count / 2))
        ->setAttribute('y', $plot['top'])->setAttribute('width', $fmt($innerWidth / $count))->setAttribute('height', $innerHeight);
    $hit->addItem(new CTag('title', true, $period['hours_with_data'] === 0
        ? _s('%1$s: no data', $periodName($period))
        : ($capacity['range'] === 'day'
            ? _s('%1$s: %2$s clients on average', $periodName($period), $number($period['clients_avg'], 1))
            : _s('%1$s: average %2$s, busiest hour %3$s clients', $periodName($period), $number($period['clients_avg'], 1),
                $number($period['clients_peak_hour'], 1)))));
    $svg->addItem($hit);
}
$root->addItem([new CTag('h2', true, _('Clients')), $svg]);

// By period: the clients and utilisation per period. Periods with data for fewer than half their hours are marked,
// since their averages rest on few samples. AP counts and the 95th percentile, which the tiles already summarise,
// are in a second table behind a disclosure.
$partial = static fn(array $period): bool => $period['hours_with_data'] > 0
    && $period['hours_with_data'] * 2 < $period['hours'];
$table = (new CTableInfo())->setHeader([_('Period'), _('Hours with data'), _('Clients, average'), _('Busiest hour'),
    _('2.4 GHz avg / peak'), _('5 GHz avg / peak'), _('6 GHz avg / peak')]);
$apTable = (new CTableInfo())->setHeader([_('Period'), _('95th percentile hour'), _('Most on one AP'),
    _('APs up, average'), _('APs down, most')]);
foreach (array_reverse($periods) as $period) {
    $bands = [];
    foreach (\Modules\WifiExplorer\Services\CapacityService::BANDS as $band) {
        $u = $period['utilisation'][$band];
        $bands[] = $u['avg'] === null && $u['max'] === null ? '—' : $percent($u['avg']).' / '.$percent($u['max']);
    }
    $hours = $period['hours_with_data'].' / '.$period['hours'];
    $row = new CRow(array_merge([$periodName($period),
        $partial($period) ? [$hours, ' ', (new CSpan(_('partial')))->addClass('zx-badge')->addClass('zx-badge-partial')] : $hours,
        $number($period['clients_avg'], 1), $number($period['clients_peak_hour'], 1)], $bands));
    $apRow = new CRow([$periodName($period), $number($period['clients_p95_hour'], 1), $number($period['clients_ap_max']),
        $number($period['aps_up_avg'], 1), $number($period['aps_down_max'])]);
    if ($period['hours_with_data'] === 0) {
        $row->addClass('we-muted');
        $apRow->addClass('we-muted');
    }
    elseif ($partial($period)) {
        $row->addClass('we-row-partial');
    }
    $table->addRow($row);
    $apTable->addRow($apRow);
}
$root->addItem([new CTag('h2', true, _('By period')), $table]);
$more = (new CTag('details', true))->addClass('we-quality');
$more->addItem(new CTag('summary', true, _('Access points and 95th percentile by period')));
$more->addItem($apTable);
$root->addItem($more);
if ($capacity['range'] === 'year') {
    $root->addItem((new CTag('p', true, _('The year view reads peaks only for utilisation, so averages per band are not shown.')))
        ->addClass('we-muted'));
}

$clusters = (new CTableInfo())->setHeader([_('Cluster'), _('Hours with data'), _('Clients, average'), _('Busiest hour'),
    _('2.4 GHz peak'), _('5 GHz peak'), _('6 GHz peak')])->setNoDataMessage(_('No visible cluster.'));
foreach ($capacity['clusters'] as $cluster) {
    if ($cluster['hours_with_data'] === 0 && !array_filter($cluster['utilisation_max'], static fn($v) => $v !== null)) {
        continue;
    }
    $clusters->addRow([new CLink($cluster['name'], (string) ($urls[$cluster['hostid']] ?? '')), $cluster['hours_with_data'],
        $number($cluster['clients_avg'], 1), $number($cluster['clients_peak_hour'], 1),
        $percent($cluster['utilisation_max']['2.4']), $percent($cluster['utilisation_max']['5']),
        $percent($cluster['utilisation_max']['6'])]);
}
$root->addItem([new CTag('h2', true, _('By cluster')), $clusters]);
