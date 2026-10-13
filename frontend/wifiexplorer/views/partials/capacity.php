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
$switcher = (new CList())->addClass('we-tabs')->setAttribute('role', 'navigation');
foreach ($ranges as $key => $name) {
    $item = new CLink($name, $link(['view'=>'capacity', 'range'=>$key === 'month' ? '' : $key]));
    if ($key === $capacity['range']) {
        $item->setAttribute('aria-current', 'page');
    }
    $switcher->addItem((new CListItem($item))->addClass($key === $capacity['range'] ? 'we-tab-active' : 'we-tab'));
}
$root->addItem($switcher);
$root->addItem((new CTag('p', true, _('From the hourly trends of each cluster\'s capacity items. Only complete observations give a value, so an hour without one is a gap, not a zero. "Busiest hour" is the highest hourly average; utilisation peaks are the highest sample any radio reported. The current hour is not in the trends yet.')))
    ->addClass('we-note'));

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
$tile = static fn(string $title, string $value, string $detail) => (new CDiv([
    (new CDiv($title))->addClass('we-tile-title'), (new CDiv($value))->addClass('we-tile-value'),
    (new CDiv($detail))->addClass('we-tile-detail')]))->addClass('we-tile');
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
            _s('%1$s radios up in the last full hour', $number(array_column($capacity['bands'], 'radios_up', 'band')[$band] ?? null))));
    }
}
$tiles->addItem($tile(_('Hours with data'), $capacity['hours_with_data'].' / '.$capacity['hours'],
    _('Hours in the range for which at least one cluster reported a complete observation.')));
$root->addItem($tiles);

// A small chart of the average and busiest-hour clients per period; gaps break the line.
$chartWidth = 720;
$chartHeight = 140;
$values = array_merge(array_column($periods, 'clients_peak_hour'), array_column($periods, 'clients_avg'));
$top = max(1.0, (float) ($maxOf($values) ?? 1));
$count = max(1, count($periods));
$x = static fn(int $i): string => number_format(($i + 0.5) * $chartWidth / $count, 1, '.', '');
$y = static fn(float $v): string => number_format($chartHeight - 4 - $v / $top * ($chartHeight - 12), 1, '.', '');
$svg = (new CTag('svg', true))->addClass('we-capacity-chart')
    ->setAttribute('viewBox', '0 0 '.$chartWidth.' '.$chartHeight)->setAttribute('role', 'img')
    ->setAttribute('aria-label', _('Clients per period: average and busiest hour'));
foreach (['clients_avg'=>'we-capacity-avg', 'clients_peak_hour'=>'we-capacity-peak'] as $field => $class) {
    $segment = [];
    foreach ($periods as $i => $period) {
        if ($period[$field] === null) {
            if (count($segment) > 1) {
                $svg->addItem((new CTag('polyline', true))->setAttribute('points', implode(' ', $segment))->addClass($class));
            }
            $segment = [];
            continue;
        }
        $segment[] = $x($i).','.$y((float) $period[$field]);
    }
    if (count($segment) > 1) {
        $svg->addItem((new CTag('polyline', true))->setAttribute('points', implode(' ', $segment))->addClass($class));
    }
}
$root->addItem([new CTag('h2', true, _('Clients')), $svg,
    (new CTag('p', true, _s('Solid: average; dashed: busiest hour. Scale 0 to %1$s.', $number($top))))->addClass('we-muted')]);

$table = (new CTableInfo())->setHeader([_('Period'), _('Hours with data'), _('Clients, average'), _('Busiest hour'),
    _('95th percentile hour'), _('Most on one AP'), _('APs up, average'), _('APs down, most'),
    _('2.4 GHz avg / peak'), _('5 GHz avg / peak'), _('6 GHz avg / peak')]);
foreach (array_reverse($periods) as $period) {
    $bands = [];
    foreach (\Modules\WifiExplorer\Services\CapacityService::BANDS as $band) {
        $u = $period['utilisation'][$band];
        $bands[] = $u['avg'] === null && $u['max'] === null ? '—' : $percent($u['avg']).' / '.$percent($u['max']);
    }
    $row = new CRow(array_merge([$periodName($period), $period['hours_with_data'].' / '.$period['hours'],
        $number($period['clients_avg'], 1), $number($period['clients_peak_hour'], 1), $number($period['clients_p95_hour'], 1),
        $number($period['clients_ap_max']), $number($period['aps_up_avg'], 1), $number($period['aps_down_max'])], $bands));
    if ($period['hours_with_data'] === 0) {
        $row->addClass('we-muted');
    }
    $table->addRow($row);
}
$root->addItem([new CTag('h2', true, _('By period')), $table]);
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
