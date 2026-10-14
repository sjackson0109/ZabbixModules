<?php
/**
 * SSIDs: each network the clusters report, merged with declared intent. The VLAN is declared, never inferred;
 * whether an AP broadcasts an SSID is inferred from cluster, AP and radio state.
 *
 * @var array $data
 * @var CDiv $root
 */
$reasons = ['ssid_state_unknown'=>_('cluster SSID state unknown'), 'not_on_cluster'=>_('not configured on the cluster'),
    'disabled'=>_('disabled on the cluster'), 'ap_down'=>_('AP down'), 'ap_state_unknown'=>_('AP state unknown'),
    'radio_state_unknown'=>_('radio state or band unknown'), 'no_radio_in_band'=>_('no radio up in an expected band')];
$states = ['broadcasting'=>_('Broadcasting'), 'not_broadcasting'=>_('Not broadcasting'), 'unknown'=>_('Unknown')];

$root->addItem($about(_('Observed comes from each cluster\'s SSID table; Declared comes from the Wi-Fi configuration.'),
    _('Declared is the VLAN and where the SSID is expected; Aruba Instant does not expose an SSID\'s VLAN over SNMP. "Broadcasting" is inferred from the cluster, AP and radio state; zone restrictions are not visible to Wi-Fi Explorer.')));

$needle = mb_strtolower($request['q']);
$table = (new CTableInfo())->setHeader([_('SSID'), _('State'), _('Hidden'), _('Clients'), _('VLAN'), _('Expected APs'),
    _('Clusters')])->setNoDataMessage($needle !== '' ? _('No SSID matches the search.')
        : _('No SSID is reported by the visible clusters or declared for the visible sites.'));
$selected = null;
foreach ($data['ssids'] as $ssid) {
    if ($ssid['ssid_uid'] === $request['ssid']) {
        $selected = $ssid;
    }
    if ($needle !== '' && strpos(mb_strtolower($ssid['name']), $needle) === false) {
        continue;
    }
    $state = $ssid['enabled'] === null
        ? ($ssid['observations'] ? _('Unknown (stale)') : _('Not seen'))
        : ($ssid['enabled'] ? _('Enabled') : _('Disabled'));
    $vlans = [];
    foreach ($ssid['vlans'] as $site => $vlan) {
        $vlans[] = $vlan.(count($ssid['vlans']) > 1 ? ' ('.$site.')' : '');
    }
    $counts = $ssid['counts'];
    $row = new CRow([new CLink($ssid['name'], $link(['view'=>'ssids', 'ssid'=>$ssid['ssid_uid']])),
        [$state, ' ', $kind('observed')],
        $ssid['hidden'] ? _('Yes') : _('No'),
        $ssid['clients_reported'] ? $ssid['clients'] : _('Not reported'),
        $vlans ? [implode(', ', $vlans), ' ', $kind('declared')] : (new CSpan(_('Unknown: not declared')))->addClass('we-muted'),
        $ssid['expected'] ? [_s('%1$s of %2$s broadcasting', $counts['broadcasting'], count($ssid['expected']))
            .($counts['unknown'] ? ', '._s('%1$s unknown', $counts['unknown']) : ''), ' ', $kind('inferred')] : '—',
        implode(', ', array_unique(array_column($ssid['observations'], 'owner_name'))) ?: '—']);
    if ($ssid['ssid_uid'] === $request['ssid']) {
        $row->addClass('we-selected');
    }
    if ($ssid['declared'] && ($ssid['enabled'] === false || $ssid['enabled'] === null && !$ssid['observations']
            || $counts['not_broadcasting'] > 0)) {
        $row->addClass('we-row-warning');
    }
    $table->addRow($row);
}
$root->addItem([new CTag('h2', true, _('SSIDs')), $table]);

if ($request['ssid'] !== '' && $selected === null) {
    $root->addItem((new CDiv(_('The selected SSID is not reported or declared in this scope.')))->addClass('msg-warning'));
}
if ($selected !== null) {
    $detail = (new CDiv())->addClass('we-detail');
    $detail->addItem(new CTag('h2', true, $selected['name']));
    $intent = (new CTableInfo())->setHeader([_('Site'), _('VLAN'), _('Expected on'), _('Bands')])
        ->setNoDataMessage(_('No intent is declared for this SSID, so its VLAN is unknown and its service path is not checked.'));
    foreach ($selected['intent'] as $row) {
        $intent->addRow([$row['site'] !== '' ? $row['site'] : _('Every site'), $row['vlan'],
            $row['expect'] === 'site' ? _('Every AP at the site')
                : ($row['expect'] === 'floors' ? _s('Floors: %1$s', implode(', ', $row['floors']))
                    : _s('%1$s listed APs', count($row['aps']))),
            $row['bands'] ? implode(', ', array_map(static fn($b) => $b.' GHz', $row['bands'])) : _('Any')]);
    }
    $detail->addItem([new CTag('h3', true, [_('Declared intent'), ' ', $kind('declared')]), $intent]);
    $observed = (new CTableInfo())->setHeader([_('Cluster'), _('Site'), _('State'), _('Hidden'), _('Clients'),
        _('Freshness'), _('Observed')])->setNoDataMessage(_('No visible cluster reports this SSID.'));
    foreach ($selected['observations'] as $row) {
        $observed->addRow([new CLink($row['owner_name'], (string) ($urls[$row['hostid']] ?? '')), $unknown($row['site']),
            $row['enabled'] ? _('Enabled') : _('Disabled'), $row['hidden'] ? _('Yes') : _('No'),
            $row['client_count'] ?? _('Not reported'), $row['freshness'], $row['observed_at'] ?? _('never')]);
    }
    $detail->addItem([new CTag('h3', true, [_('Observed on'), ' ', $kind('observed')]), $observed]);
    $expected = (new CTableInfo())->setHeader([_('Access point'), _('State'), _('Reason'), _('Wired uplink'),
        _('Service path')])->setNoDataMessage(_('No visible AP is expected to broadcast this SSID.'));
    foreach ($selected['expected'] as $row) {
        $uplink = $byUid[$row['ap_uid']]['uplink'] ?? null;
        $expected->addRow([new CLink($apName($row['ap_uid']), $link(['ap'=>$row['ap_uid']])),
            [(new CSpan($states[$row['status']]))->addClass('we-path-'.$row['status']), ' ', $kind($row['kind'])],
            $row['reason'] !== null ? ($reasons[$row['reason']] ?? $row['reason']) : '',
            $uplink !== null && $uplink['hostid'] !== null
                ? ($uplink['switch_name'] ?? '?').' '.($uplink['interface_name'] ?? '?') : _('Unresolved'),
            $row['vlan'] !== null
                ? new CLink(_('Check VLAN path'), $link(['view'=>'paths', 'ssid'=>$selected['ssid_uid']]))
                : _('VLAN not declared')]);
    }
    $detail->addItem([new CTag('h3', true, _('Expected access points')), $expected,
        new CLink(_('Clear selection'), $link(['view'=>'ssids']))]);
    $root->addItem($detail);
}
