<?php
/**
 * Clients: who is associated now, a search over what the viewer may see, and one client's trace and sampled
 * timeline. Identifiers are shown exactly as the producer's privacy policy left them.
 *
 * @var array $data
 * @var CDiv $root
 */
$clients = $data['clients'];
$policies = ['full'=>_('full identifiers'), 'partial'=>_('partial (MAC vendor prefix only)'),
    'pseudonymised'=>_('pseudonymised')];
$root->addItem($about(_('Clients associated now, from each cluster\'s client snapshot.'),
    _('Identifiers follow the template\'s privacy policy (the WE.CLIENT.IDENTIFIERS macro): with partial or pseudonymised identifiers a full MAC address, IP address or name is not stored and cannot be searched. The SSID of a client is not reported by Aruba Instant over SNMP.')));

$sources = (new CTableInfo())->setHeader([_('Cluster'), _('Clients'), _('Identifiers'), _('Freshness'), _('Observed')])
    ->setNoDataMessage(_('No visible cluster collects clients.'));
foreach ($clients['sources'] as $source) {
    $sources->addRow([new CLink($source['name'], (string) ($urls[$source['hostid']] ?? '')),
        $source['clients'].($source['over_limit'] ? ' '._('(over the snapshot limit, partial)') : ''),
        $source['policy'] !== null ? ($policies[$source['policy']] ?? $source['policy']) : '—',
        $source['freshness'], $source['observed_at'] ?? _('never')]);
}
// A privacy warning, so it is set apart from the explanatory text above it and links to where it is fixed.
$unkeyed = array_filter($clients['sources'], static fn($s) => $s['unkeyed']);
if ($unkeyed) {
    $hosts = [];
    foreach ($unkeyed as $source) {
        $hosts[] = new CLink($source['name'], 'zabbix.php?'.http_build_query(['action'=>'host.edit',
            'hostid'=>$source['hostid']]));
        $hosts[] = ', ';
    }
    array_pop($hosts);
    $root->addItem((new CDiv([(new CSpan(_('Client IDs are not keyed.')))->addClass('zx-callout-title'), ' ',
        _('Pseudonymised client IDs from these clusters could be traced back to MAC addresses until the {$WE.CLIENT.KEY} secret macro is set on the template or host:'),
        ' ', $hosts]))->addClass('zx-callout')->addClass('zx-callout-warning')->setAttribute('role', 'note'));
}
$details = (new CTag('details', true))->addClass('we-quality');
$details->addItem(new CTag('summary', true, _('Client sources')));
$details->addItem($sources);
$root->addItem($details);

$radioNames = [];
foreach ($data['aps'] as $ap) {
    foreach ($ap['radios'] as $radio) {
        $radioNames[$radio['radio_uid']] = ($radio['band'] !== null ? $radio['band'].' GHz' : _('band unknown')).' / '
            .($radio['channel'] ?? '?');
    }
}
$duration = static fn(?int $s): string => $s === null ? _('Unknown') : convertUnitsS($s);
$label = static fn(array $c): string => $c['name'] ?? $c['mac_address'] ?? substr($c['client_uid'], 7, 8);

if ($clients['selection_missing']) {
    $root->addItem((new CDiv(_('The selected client is not associated now with a visible AP, or is not visible to you.')))
        ->addClass('msg-warning'));
}
$selected = $clients['selected'];
if ($selected !== null) {
    $detail = (new CDiv())->addClass('we-detail');
    $detail->addItem(new CTag('h2', true, $label($selected)));
    $trace = (new CTableInfo())->setHeader([_('Step'), _('What'), _('Basis')]);
    $trace->addRow([_('Client'), implode(', ', array_filter([$selected['mac_address'], $selected['ip_address'],
        $selected['name']])).' · '._s('SNR %1$s dB', $selected['snr_db'] ?? '?').' · '
        ._s('connected %1$s', $duration($selected['connected_s'])), $kind('observed')]);
    $ap = $selected['ap_uid'] !== null ? $byUid[$selected['ap_uid']] : null;
    $trace->addRow([_('Access point'), $ap !== null ? new CLink($apName($ap['ap_uid']), $link(['ap'=>$ap['ap_uid']]))
        : _('Not matched to a visible AP'), $kind($ap !== null ? 'observed' : 'not_collected')]);
    $trace->addRow([_('Radio'), $selected['radio_uid'] !== null
        ? ($radioNames[$selected['radio_uid']] ?? '?').' · '._s('BSSID %1$s', $selected['bssid'] ?? '?') : _('Unknown'),
        $kind($selected['radio_basis'] === 'bssid' ? 'observed' : ($selected['radio_basis'] !== null ? 'inferred' : 'not_collected'))]);
    $uplink = $ap['uplink'] ?? null;
    $trace->addRow([_('Wired uplink'), $uplink !== null && $uplink['hostid'] !== null
        ? ($uplink['switch_name'] ?? '?').' '.($uplink['interface_name'] ?? '?')
        : ($uplink === null ? \Modules\WifiExplorer\Services\WifiErrors::wired($data['wired']['reason']) : _('Unresolved')),
        $kind($uplink !== null && $uplink['state'] === 'confirmed' ? 'observed' : 'inferred')]);
    foreach ($ap['ssids'] ?? [] as $ssidUid => $state) {
        $path = $data['paths'][$ssidUid]['results'][$ap['ap_uid']] ?? null;
        if ($path === null) {
            continue;
        }
        $name = array_column($data['ssids'], 'name', 'ssid_uid')[$ssidUid] ?? $ssidUid;
        $trace->addRow([_s('VLAN %1$s path', $path['vlan']),
            [new CLink($name, $link(['view'=>'paths', 'ssid'=>$ssidUid])), ': ',
                $toned([
                    'complete'=>_('Complete'), 'failed'=>_('Failed'), 'partial'=>_('Partial')][$path['status']] ?? _('Unknown'),
                    $path['status'])], $kind('observed')]);
    }
    $detail->addItem([new CTag('h3', true, _('Trace')), $trace]);
    $detail->addItem(new CTag('p', true, _('The client\'s SSID is not reported, so every SSID path of its AP is listed.')));

    $timeline = $data['clients']['timeline'];
    $detail->addItem(new CTag('h3', true, [_('Sampled association timeline'), ' ', $kind('inferred')]));
    if (!$timeline['available'] || $timeline['samples'] === []) {
        $detail->addItem((new CTag('p', true, $timeline['reason'] === 'history_too_large'
            ? _('The client snapshots of this cluster are too large to read for a timeline.')
            : _('No client snapshot history is readable for this window.')))->addClass('zx-muted'));
    }
    else {
        $changes = ['appeared'=>_('Appeared'), 'left'=>_('Not in the snapshot'), 'ap_changed'=>_('Associated with another AP'),
            'bssid_changed'=>_('Changed BSSID on the same AP')];
        $table = (new CTableInfo())->setHeader([_('Between'), _('Change'), _('From'), _('To')])
            ->setNoDataMessage(_s('No association change between the %1$s samples.', count($timeline['samples'])));
        foreach ($timeline['changes'] as $change) {
            $table->addRow([zbx_date2str(DATE_TIME_FORMAT_SECONDS, $change['between'][0]).' – '
                    .zbx_date2str(DATE_TIME_FORMAT_SECONDS, $change['between'][1]),
                $changes[$change['type']],
                $change['from_ap'] !== null ? $apName($change['from_ap']).' ('.($change['from_bssid'] ?? '?').')' : '—',
                $change['to_ap'] !== null ? $apName($change['to_ap']).' ('.($change['to_bssid'] ?? '?').')' : '—']);
        }
        $detail->addItem(new CTag('p', true, _s('%1$s samples over the last %2$s%3$s. A change is seen between two samples; when exactly it happened, and whether there were others in between, is not known.',
            count($timeline['samples']), convertUnitsS($timeline['window_s']), $timeline['bounded'] ? ' '._('(bounded)') : '')));
        $detail->addItem($table);
    }
    $detail->addItem(new CLink(_('Clear selection'), $link(['view'=>'clients', 'q'=>$request['q']])));
    $root->addItem($detail);
}

$table = (new CTableInfo())->setHeader([_('Client'), _('MAC address'), _('IP address'), _('Access point'), _('Radio'),
    _('SNR'), _('Connected')])
    ->setNoDataMessage($request['q'] !== '' ? _('No current client matches the search.') : _('No client is associated now.'));
foreach ($clients['clients'] as $client) {
    $row = new CRow([new CLink($label($client), $link(['view'=>'clients', 'client'=>$client['client_uid'], 'q'=>$request['q']])),
        $client['mac_address'] ?? '—', $client['ip_address'] ?? '—',
        $client['ap_uid'] !== null ? new CLink($apName($client['ap_uid']), $link(['ap'=>$client['ap_uid']])) : _('Unknown'),
        $client['radio_uid'] !== null ? $radioNames[$client['radio_uid']] ?? '?' : _('Unknown'),
        $client['snr_db'] !== null ? $client['snr_db'].' dB' : _('Unknown'), $duration($client['connected_s'])]);
    if ($client['client_uid'] === $request['client']) {
        $row->addClass('we-selected');
    }
    $table->addRow($row);
}
$root->addItem([new CTag('h2', true, _s('Clients now (%1$s)', $clients['matched'].($clients['matched'] !== $clients['total']
    ? ' '._s('of %1$s', $clients['total']) : ''))), $table]);
if ($clients['matched'] > count($clients['clients'])) {
    $root->addItem((new CTag('p', true, _s('The first %1$s are listed; search to narrow.', count($clients['clients']))))
        ->addClass('zx-muted'));
}
