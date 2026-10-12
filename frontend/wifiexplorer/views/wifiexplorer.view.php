<?php
/**
 * Monitoring -> Wi-Fi Explorer. Server-rendered from the current user's permission-filtered model: the site
 * selector, the overview, findings, the AP inventory, the selected AP's radios and the data quality of every
 * Wi-Fi data source. Device strings reach the page only through Zabbix's escaping HTML classes.
 *
 * @var array $data
 */
use Modules\WifiExplorer\Services\WifiErrors;

$request = $data['request'];
$page = (new CHtmlPage())->setTitle(_('Wi-Fi Explorer'));
$root = (new CDiv())->addClass('we-explorer');

$link = static function (array $params): string {
    return 'zabbix.php?'.http_build_query(['action'=>'wifiexplorer.view'] + array_filter($params,
        static fn($value) => $value !== '' && $value !== null));
};
$unknown = static fn($value, string $suffix = '') => $value === null || $value === '' ? _('Unknown') : $value.$suffix;
$labels = [
    'state_not_collected'=>_('state not collected'), 'absent_from_state'=>_('not in the latest state'),
    'state_stale'=>_('state is stale'), 'state_unknown'=>_('state age unknown')
];
$status = static function (string $value, ?string $reason = null) use ($labels): CSpan {
    $text = $value === 'up' ? _('Up') : ($value === 'down' ? _('Down') : _('Unknown'));
    if ($reason !== null) {
        $text .= ' ('.($labels[$reason] ?? $reason).')';
    }
    return (new CSpan($text))->addClass('we-status')->addClass('we-status-'.$value);
};

// Scope: a site narrows the view; changing it drops the AP selection, which belongs to one scope.
$sites = $data['sites'];
$select = (new CSelect('site'))->setId('we-site')->setFocusableElementId('we-site-button')
    ->addOption(new CSelectOption('', _('All')));
foreach ($sites as $site) {
    $select->addOption(new CSelectOption($site, $site));
}
if ($request['site'] !== '' && !in_array($request['site'], $sites, true)) {
    $select->addOption(new CSelectOption($request['site'], $request['site']));
}
$select->setValue($request['site']);
$form = (new CForm('get'))->setAction('zabbix.php')->addClass('we-scope')->setAttribute('aria-label', _('Scope'));
$form->addVar('action', 'wifiexplorer.view');
$form->addItem((new CDiv([new CLabel(_('Site'), 'we-site-button'), $select]))->addClass('we-scope-field'));
$form->addItem(new CSubmit('apply', _('Apply')));
$root->addItem($form);

if (isset($data['error'])) {
    $root->addItem((new CDiv(WifiErrors::message($data['error'])))->addClass('msg-bad'));
    $page->addItem($root)->show();
    return;
}

if ($data['owners'] === []) {
    $root->addItem((new CDiv([
        new CTag('p', true, _('No Wi-Fi data source is visible to you in this scope.')),
        new CTag('p', true, _('Link the "Wi-Fi Explorer - Aruba Instant VC by SNMP" template to one host per Aruba Instant cluster, pointed at the cluster\'s virtual controller address, and check that your user group can read that host.'))
    ]))->addClass('we-empty'));
    $page->addItem($root)->show();
    return;
}

$overview = $data['overview'];
$tile = static function (string $title, $value, string $detail = '', string $class = ''): CDiv {
    $tile = (new CDiv([(new CDiv($title))->addClass('we-tile-title'), (new CDiv((string) $value))->addClass('we-tile-value'),
        (new CDiv($detail))->addClass('we-tile-detail')]))->addClass('we-tile');
    return $class !== '' ? $tile->addClass($class) : $tile;
};
$aps = $overview['aps'];
$radios = $overview['radios'];
$bands = $overview['bands'];
$bandText = [];
foreach (['2.4'=>'2.4 GHz', '5'=>'5 GHz', '6'=>'6 GHz', 'unknown'=>_('unknown')] as $band => $name) {
    if ($bands[$band] > 0) {
        $bandText[] = $name.': '.$bands[$band];
    }
}
$utilisation = [];
foreach ($overview['utilisation'] as $band => $summary) {
    $utilisation[] = _s('%1$s average %2$s%%, max %3$s%%', $band === 'unknown' ? _('Unknown band') : $band.' GHz',
        $summary['average'], $summary['max']);
}
$datasets = $overview['datasets'];
$tiles = (new CDiv())->addClass('we-tiles');
$tiles->addItem($tile(_('Access points'), $aps['total'],
    _s('%1$s up, %2$s down, %3$s unknown, %4$s degraded', $aps['up'], $aps['down'], $aps['unknown'], $aps['degraded']),
    $aps['down'] > 0 ? 'we-tile-warning' : ''));
$tiles->addItem($tile(_('Radios'), $radios['total'],
    _s('%1$s up, %2$s down, %3$s unknown', $radios['up'], $radios['down'], $radios['unknown'])
        .($bandText ? ' · '.implode(', ', $bandText) : '')));
$tiles->addItem($tile(_('Channel utilisation'), _s('%1$s high', $overview['high_utilisation_radios']),
    ($utilisation ? implode('; ', $utilisation) : _('No current utilisation'))
        .' · '._s('high is %1$s%% or more', $overview['high_utilisation_threshold']),
    $overview['high_utilisation_radios'] > 0 ? 'we-tile-warning' : ''));
$tiles->addItem($tile(_('Findings'), $overview['findings']['warning'] + $overview['findings']['info'],
    _s('%1$s warning, %2$s info', $overview['findings']['warning'], $overview['findings']['info']),
    $overview['findings']['warning'] > 0 ? 'we-tile-warning' : ''));
$tiles->addItem($tile(_('Data sources'), count($data['owners']),
    _s('%1$s of %2$s datasets current, %3$s stale, %4$s failed, %5$s unsupported', $datasets['current'],
        $datasets['total'], $datasets['stale'], $datasets['failed'], $datasets['unsupported']),
    $datasets['stale'] + $datasets['failed'] > 0 ? 'we-tile-warning' : ''));
$root->addItem($tiles);

$notAvailable = ['clients'=>_('clients'), 'ssids'=>_('SSIDs'), 'rogue_aps'=>_('rogue APs'),
    'wired_uplinks'=>_('wired uplinks'), 'vlan_paths'=>_('SSID to VLAN paths'), 'poe'=>_('PoE'),
    'auth_failures'=>_('authentication failures')];
$root->addItem((new CTag('p', true, _('Not collected yet, so not counted: ')
    .implode(', ', array_map(static fn($key) => $notAvailable[$key] ?? $key, $overview['not_available'])).'.'))
    ->addClass('we-not-available'));

$byUid = array_column($data['aps'], null, 'ap_uid');
$urls = array_column($data['owners'], 'dashboard_url', 'hostid');
$radioAps = [];
foreach ($data['aps'] as $ap) {
    foreach ($ap['radios'] as $radio) {
        $radioAps[$radio['radio_uid']] = $ap['ap_uid'];
    }
}
if ($data['selection_missing']) {
    $root->addItem((new CDiv(_('The selected access point is not in this scope or is not visible to you.')))
        ->addClass('msg-warning'));
}

// Selected AP: its identity, state and radios.
if ($data['selected_ap'] !== '') {
    $ap = $byUid[$data['selected_ap']];
    $detail = (new CDiv())->addClass('we-detail');
    $detail->addItem(new CTag('h2', true, $ap['name'] ?? _('Unnamed access point')));
    $facts = (new CTableInfo())->setHeader([_('Status'), _('Model'), _('Serial'), _('MAC address'), _('IP address'),
        _('Firmware'), _('Uptime'), _('CPU'), _('Memory used'), _('Data source')]);
    $facts->addRow([$status($ap['status'], $ap['status_reason']), $unknown($ap['model']), $unknown($ap['serial']),
        $unknown($ap['mac_address']), $unknown($ap['ip_address']),
        $ap['firmware'] ?? ($ap['cluster_firmware'] !== null ? $ap['cluster_firmware'].' '._('(cluster)') : _('Unknown')),
        $ap['uptime_s'] !== null ? zbx_date2age(time() - $ap['uptime_s']) : _('Unknown'),
        $unknown($ap['cpu_percent'], '%'), $unknown($ap['memory_used_percent'], '%'),
        new CLink($ap['owner_name'], (string) ($urls[$ap['owner_hostid']] ?? ''))]);
    $detail->addItem($facts);
    $radioTable = (new CTableInfo())->setHeader([_('Radio'), _('Status'), _('Band'), _('Channel'), _('Width'),
        _('Utilisation'), _('Tx power'), _('Noise floor'), _('BSSID'), _('Observed')])
        ->setNoDataMessage(_('This AP reports no radios.'));
    foreach ($ap['radios'] as $radio) {
        $row = new CRow([$unknown($radio['radio_index']), $status($radio['status'], $radio['status_reason']),
            $radio['band'] !== null ? $radio['band'].' GHz' : _('Unknown'), $unknown($radio['channel']),
            $radio['channel_width'] !== null ? $radio['channel_width'].' MHz' : _('Unknown'),
            $radio['utilisation_percent'] !== null
                ? _s('%1$s%% over %2$s s', $radio['utilisation_percent'], $radio['utilisation_window_s'] ?? '?') : _('Unknown'),
            $unknown($radio['tx_power_dbm'], ' dBm'), $unknown($radio['noise_floor_dbm'], ' dBm'),
            $unknown($radio['bssid']), $radio['state_freshness'].' / '.($radio['state_observed_at'] ?? _('never'))]);
        if ($radio['status'] === 'up' && $radio['utilisation_percent'] !== null
                && $radio['utilisation_percent'] >= $overview['high_utilisation_threshold']) {
            $row->addClass('we-row-warning');
        }
        $radioTable->addRow($row);
    }
    $detail->addItem([new CTag('h3', true, _('Radios')), $radioTable,
        new CLink(_('Clear selection'), $link(['site'=>$request['site']]))]);
    $root->addItem($detail);
}

// Findings: warnings first, each with what it is about, why, and how fresh the evidence is.
$findings = (new CTableInfo())->setHeader([_('Severity'), _('Finding'), _('Reason'), _('Evidence'), _('Next step')])
    ->setNoDataMessage(_('No findings from the current observations.'));
foreach ($data['findings'] as $finding) {
    $apUid = $finding['object_type'] === 'radio' ? ($radioAps[$finding['object_id']] ?? null) : $finding['object_id'];
    $title = in_array($finding['object_type'], ['ap', 'radio'], true) && isset($byUid[$apUid])
        ? new CLink($finding['title'], $link(['site'=>$request['site'], 'ap'=>$apUid]))
        : $finding['title'];
    $findings->addRow([(new CSpan($finding['severity'] === 'warning' ? _('Warning') : _('Info')))
            ->addClass('we-severity-'.$finding['severity']), $title, $finding['reason'],
        $finding['freshness'].($finding['last_observed'] !== null ? ' / '.$finding['last_observed'] : ''),
        $finding['remediation'] ?? '']);
}
$root->addItem([new CTag('h2', true, _('Findings')), $findings]);

// AP inventory: every visible AP, its effective state and radios at a glance.
$inventory = (new CTableInfo())->setHeader([_('Access point'), _('Site'), _('Status'), _('Radios'), _('Model'),
    _('IP address'), _('Data source')])->setNoDataMessage(_('The visible data sources list no access points.'));
foreach ($data['aps'] as $ap) {
    $summary = [];
    foreach ($ap['radios'] as $radio) {
        $summary[] = ($radio['band'] !== null ? $radio['band'] : '?').'/'.($radio['channel'] ?? '?').' '
            .($radio['status'] === 'up' ? '' : '('.$radio['status'].')').($radio['utilisation_percent'] !== null
                && $radio['status'] === 'up' ? $radio['utilisation_percent'].'%' : '');
    }
    $row = new CRow([new CLink($ap['name'] ?? _('Unnamed access point'), $link(['site'=>$request['site'], 'ap'=>$ap['ap_uid']])),
        $ap['site'] !== '' ? $ap['site'] : _('Unknown'),
        [$status($ap['status'], $ap['status_reason']), $ap['degraded'] ? ' '._('degraded') : ''],
        $summary ? implode(', ', array_map('trim', $summary)) : _('None reported'), $unknown($ap['model']),
        $unknown($ap['ip_address']), $ap['owner_name']]);
    if ($ap['ap_uid'] === $data['selected_ap']) {
        $row->addClass('we-selected');
    }
    $inventory->addRow($row);
}
$root->addItem([new CTag('h2', true, _('Access points')), $inventory]);

// Data quality: each source's datasets, so an empty table is never mistaken for "no problems".
$names = array_column($data['owners'], 'name', 'hostid');
$roles = array_column($data['owners'], 'role', 'hostid');
$quality = (new CTableInfo())->setHeader([_('Data source'), _('Role'), _('Dataset'), _('Status'), _('Freshness'),
    _('Observed'), _('Errors')])->setNoDataMessage(_('No collection items found on the visible data sources.'));
foreach ($data['quality'] as $row) {
    $hostid = $row['hostid'];
    $quality->addRow([new CLink($names[$hostid] ?? $hostid, (string) ($urls[$hostid] ?? '')),
        str_replace('_', ' ', $roles[$hostid] ?? 'unknown'), $row['dataset'], $row['status'], $row['freshness'],
        $row['observed_at'] ?? _('never'), implode(', ', array_merge($row['errors'], $row['warnings']))]);
}
$details = (new CTag('details', true))->addClass('we-quality');
$details->addItem(new CTag('summary', true, _('Data quality')));
$details->addItem($quality);
$root->addItem($details);

$page->addItem($root)->show();
