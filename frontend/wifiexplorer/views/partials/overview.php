<?php
/**
 * Overview: the site tiles, the selected AP, findings, the AP inventory and data quality.
 *
 * @var array $data
 * @var CDiv $root
 */
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

$rf = $data['rf'];
$tiles->addItem($tile(_('RF neighbours'), $rf['current_total'],
    _s('%1$s flagged by an AP, %2$s unknown, %3$s known, %4$s managed', $rf['counts']['flagged'], $rf['counts']['unknown'],
        $rf['counts']['known_neighbour'] + $rf['counts']['known_external'], $rf['counts']['managed'])
        .($rf['stale'] > 0 ? ' · '._s('%1$s more only in stale data', $rf['stale']) : '')
        .($rf['observers'] ? '' : ' · '._('no AP is polled for its RF view')),
    $rf['counts']['flagged'] > 0 ? 'we-tile-warning' : ''));
$notAvailable = ['poe'=>_('PoE'), 'auth_failures'=>_('authentication failures'), 'retry_rates'=>_('retry and error rates')];
$root->addItem((new CTag('p', true, _('Not exposed by the current sources, so not counted: ')
    .implode(', ', array_map(static fn($key) => $notAvailable[$key] ?? $key, $overview['not_available'])).'.'))
    ->addClass('we-not-available'));

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
        _('Firmware'), _('Uptime'), _('CPU'), _('Memory used'), _('Clients'), _('Placement'), _('Data source')]);
    $facts->addRow([$status($ap['status'], $ap['status_reason']), $unknown($ap['model']), $unknown($ap['serial']),
        $unknown($ap['mac_address']), $unknown($ap['ip_address']),
        $ap['firmware'] ?? ($ap['cluster_firmware'] !== null ? $ap['cluster_firmware'].' '._('(cluster)') : _('Unknown')),
        $ap['uptime_s'] !== null ? zbx_date2age(time() - $ap['uptime_s']) : _('Unknown'),
        $unknown($ap['cpu_percent'], '%'), $unknown($ap['memory_used_percent'], '%'),
        $ap['clients'] !== null ? $ap['clients'] : _('Unknown'),
        $ap['placement'] !== null
            ? [$kind('configured'), ' ', new CLink(array_column($data['floors']['floors'], 'name', 'floor_id')[$ap['placement']['floor_id']]
                ?? $ap['placement']['floor_id'], $link(['view'=>'floors', 'floor'=>$ap['placement']['floor_id'], 'ap'=>$ap['ap_uid']]))]
            : _('Unplaced'),
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
    $detail->addItem([new CTag('h3', true, _('Radios')), $radioTable]);
    $detail->addItem(new CTag('h3', true, _('Wired uplink')));
    $uplink = $ap['uplink'];
    $uplinkStates = ['confirmed'=>_('Confirmed by the AP and the switch'), 'switch_only'=>_('Reported by the switch'),
        'ap_only'=>_('Reported by the AP'), 'conflicting'=>_('The AP and the switch disagree'),
        'ambiguous'=>_('Seen on more than one switch port'), 'unresolved'=>_('Unresolved')];
    $bases = ['chassis_mac'=>_('LLDP chassis MAC is the AP\'s MAC'), 'management_address'=>_('LLDP management address is the AP\'s address'),
        'ap_lldp'=>_('the AP\'s own LLDP')];
    if ($uplink === null) {
        $detail->addItem((new CTag('p', true, \Modules\WifiExplorer\Services\WifiErrors::wired($data['wired']['reason'] ?? null)))->addClass('we-muted'));
    }
    else {
        $port = (new CTableInfo())->setHeader([_('State'), _('Switch port'), _('Link'), _('VLANs on the port'),
            _('Matched by'), _('Freshness')]);
        $vlan = $uplink['vlan'] ?? null;
        $port->addRow([[$uplinkStates[$uplink['state']], ' ', $kind($uplink['state'] === 'confirmed' ? 'observed' : 'inferred')],
            $uplink['hostid'] !== null
                ? new CLink(($uplink['switch_name'] ?? '?').' '.($uplink['interface_name'] ?? '?'),
                    (string) ($uplink['explorer_url'] ?? ''))
                : _('None'),
            $uplink['hostid'] !== null ? $status($uplink['port_freshness'] === 'current'
                ? (string) ($uplink['oper_status'] ?? 'unknown') : 'unknown') : '—',
            $vlan !== null ? _s('%1$s, native %2$s, carries %3$s', $vlan['mode'], $vlan['pvid'] ?? '?',
                $vlan['carried'] !== '' ? $vlan['carried'] : _('none')) : _('Unknown'),
            $uplink['basis'] !== null ? $bases[$uplink['basis']] ?? $uplink['basis'] : '—',
            $uplink['freshness']]);
        $detail->addItem($port);
    }
    if ($ap['ssids']) {
        $ssidNames = array_column($data['ssids'], 'name', 'ssid_uid');
        $list = [];
        foreach ($ap['ssids'] as $ssidUid => $row) {
            $path = $data['paths'][$ssidUid]['results'][$ap['ap_uid']] ?? null;
            $list[] = new CLink(($ssidNames[$ssidUid] ?? $ssidUid).': '.str_replace('_', ' ', $row['status'])
                .($path !== null ? ', '._s('VLAN %1$s path %2$s', $path['vlan'], $path['status']) : ''),
                $link(['view'=>$path !== null ? 'paths' : 'ssids', 'ssid'=>$ssidUid]));
            $list[] = ' · ';
        }
        array_pop($list);
        $detail->addItem([new CTag('h3', true, [_('SSIDs'), ' ', $kind('inferred')]), new CTag('p', true, $list)]);
    }
    $detail->addItem(new CLink(_('Clear selection'), $link([])));
    $root->addItem($detail);
}

// Findings: warnings first, each with what it is about, why, and how fresh the evidence is.
$findings = (new CTableInfo())->setHeader([_('Severity'), _('Finding'), _('Reason'), _('Evidence'), _('Next step')])
    ->setNoDataMessage($data['wired']['available']
        ? _('No findings from the current observations.')
        : _('No findings from the current observations; uplink and VLAN path findings need the wired model:').' '
            .\Modules\WifiExplorer\Services\WifiErrors::wired($data['wired']['reason']));
foreach ($data['findings'] as $finding) {
    $apUid = $finding['object_type'] === 'radio' ? ($radioAps[$finding['object_id']] ?? null) : $finding['object_id'];
    $title = in_array($finding['object_type'], ['ap', 'radio'], true) && isset($byUid[$apUid])
        ? new CLink($finding['title'], $link(['ap'=>$apUid]))
        : ($finding['object_type'] === 'bssid' ? new CLink($finding['title'], $link(['view'=>'rf']))
        : ($finding['object_type'] === 'ssid' ? new CLink($finding['title'], $link(['view'=>strpos($finding['rule'], 'wifi_path_') === 0
            ? 'paths' : 'ssids', 'ssid'=>$finding['object_id']]))
        : ($finding['object_type'] === 'event' ? new CLink($finding['title'], $link(['view'=>'events', 'event'=>$finding['object_id']]))
        : $finding['title'])));
    $findings->addRow([(new CSpan($finding['severity'] === 'warning' ? _('Warning') : _('Info')))
            ->addClass('we-severity-'.$finding['severity']), $title, $finding['reason'],
        $finding['freshness'].($finding['last_observed'] !== null ? ' / '.$finding['last_observed'] : ''),
        $finding['remediation'] ?? '']);
}
$root->addItem([new CTag('h2', true, _('Findings')), $findings]);

// AP inventory: every visible AP, its effective state and radios at a glance.
$inventory = (new CTableInfo())->setHeader([_('Access point'), _('Site'), _('Status'), _('Radios'), _('Clients'),
    _('Placement'), _('Model'), _('IP address'), _('Data source')])
    ->setNoDataMessage($request['q'] !== '' ? _('No access point matches the search.')
        : _('The visible data sources list no access points.'));
$floorNames = array_column($data['floors']['floors'], 'name', 'floor_id');
$needle = mb_strtolower($request['q']);
$matches = static function (array $ap) use ($needle): bool {
    if ($needle === '') {
        return true;
    }
    $fields = [$ap['name'], $ap['model'], $ap['serial'], $ap['ip_address'], $ap['mac_address'], $ap['site']];
    foreach ($ap['radios'] as $radio) {
        $fields[] = $radio['bssid'];
        $fields[] = $radio['channel'] !== null ? 'ch'.$radio['channel'] : null;
        $fields[] = $radio['channel'] !== null ? (string) $radio['channel'] : null;
    }
    foreach ($fields as $field) {
        if ($field !== null && strpos(mb_strtolower((string) $field), $needle) !== false) {
            return true;
        }
    }
    return false;
};
foreach (array_filter($data['aps'], $matches) as $ap) {
    $summary = [];
    foreach ($ap['radios'] as $radio) {
        $summary[] = ($radio['band'] !== null ? $radio['band'] : '?').'/'.($radio['channel'] ?? '?').' '
            .($radio['status'] === 'up' ? '' : '('.$radio['status'].')').($radio['utilisation_percent'] !== null
                && $radio['status'] === 'up' ? $radio['utilisation_percent'].'%' : '');
    }
    $row = new CRow([new CLink($ap['name'] ?? _('Unnamed access point'), $link(['ap'=>$ap['ap_uid'], 'q'=>$request['q']])),
        $ap['site'] !== '' ? $ap['site'] : _('Unknown'),
        [$status($ap['status'], $ap['status_reason']), $ap['degraded'] ? ' '._('degraded') : ''],
        $summary ? implode(', ', array_map('trim', $summary)) : _('None reported'),
        $ap['clients'] !== null ? $ap['clients'] : _('Unknown'),
        $ap['placement'] !== null
            ? new CLink($floorNames[$ap['placement']['floor_id']] ?? $ap['placement']['floor_id'],
                $link(['view'=>'floors', 'floor'=>$ap['placement']['floor_id'], 'ap'=>$ap['ap_uid']]))
            : _('Unplaced'),
        $unknown($ap['model']),
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

