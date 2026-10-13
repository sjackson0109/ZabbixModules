<?php
/**
 * RF neighbours: what each polled AP hears, grouped by BSSID, with the AP's own classification kept as evidence
 * and Wi-Fi Explorer's evidence-based class beside it. Nothing here is called malicious.
 *
 * @var array $data
 * @var CDiv $root
 */
$rf = $data['rf'];
$classNames = ['managed'=>_('Managed'), 'known_external'=>_('Known external'), 'known_neighbour'=>_('Known neighbour'),
    'flagged'=>_('Flagged by an AP'), 'unknown'=>_('Unknown')];

$root->addItem((new CTag('p', true, _('Each row is a network the visible APs hear. "Flagged by an AP" repeats the detecting AP\'s own classification (for example suspected unsecure); it is evidence to investigate, not proof of a threat. An unknown network is not a rogue by itself. "Heard best by" shows which AP hears it most strongly; it is not a location.')))
    ->addClass('we-note'));

$observers = (new CTableInfo())->setHeader([_('Polled host'), _('AP'), _('Matched by'), _('Detections'), _('Freshness'),
    _('Observed')])->setNoDataMessage(_('No AP is polled for its own RF view. Link "Wi-Fi Explorer - Aruba Instant AP by SNMP" to a host per AP, at the AP\'s own address.'));
$basis = ['address'=>_('polled address'), 'host_name'=>_('host name')];
foreach ($rf['observers'] as $observer) {
    $observers->addRow([new CLink($observer['name'], (string) ($urls[$observer['hostid']] ?? '')),
        $observer['ap_uid'] !== null ? new CLink($apName($observer['ap_uid']), $link(['ap'=>$observer['ap_uid']]))
            : _('Not matched to a visible AP'),
        $observer['basis'] !== null ? $basis[$observer['basis']] : '—',
        $observer['detections'].($observer['bounded'] ? ' '._('(strongest kept)') : ''),
        $observer['freshness'], $observer['observed_at'] ?? _('never')]);
}
$root->addItem([new CTag('h2', true, _('Observing APs')), $observers]);

$needle = mb_strtolower($request['q']);
$table = (new CTableInfo())->setHeader([_('SSID'), _('BSSID'), _('Class'), _('AP classification'), _('Band / channel'),
    _('Encryption'), _('Best SNR'), _('Heard best by'), _('Heard by'), _('Last seen')])
    ->setNoDataMessage($needle !== '' ? _('No neighbour matches the search.') : _('No neighbouring networks observed.'));
$shown = 0;
foreach ($rf['neighbours'] as $row) {
    if ($needle !== '' && strpos(mb_strtolower(($row['ssid'] ?? '').' '.$row['bssid'].' '.$row['class'].' ch'
            .($row['channel'] ?? '')), $needle) === false) {
        continue;
    }
    ++$shown;
    $best = $row['heard_best_by'];
    $tr = new CRow([$row['ssid'] ?? (new CSpan(_('Hidden')))->addClass('we-muted'), $row['bssid'],
        [(new CSpan($classNames[$row['class']]))->addClass('we-class-'.$row['class']), ' ',
            $kind($row['class_basis']), $row['known_label'] ? ' '.$row['known_label'] : ''],
        $row['labels'] ? implode(', ', array_map(static fn($l) => str_replace('_', ' ', $l), array_keys($row['labels']))) : '—',
        ($row['band'] !== null ? $row['band'].' GHz' : '?').' / '.($row['channel'] ?? '?')
            .($row['channel_width'] !== null ? ' ('.$row['channel_width'].' MHz)' : ''),
        $row['encryption'] ?? '—', $row['best_snr'] !== null ? $row['best_snr'].' dB' : '?',
        $best === null ? '—' : (strpos($best, 'host:') === 0 ? _('an unmatched host') : new CLink($apName($best), $link(['ap'=>$best]))),
        count($row['observers']),
        [$row['last_seen'] ?? _('never'), $row['current'] ? '' : [' ', (new CSpan(_('stale')))->addClass('we-muted')]]]);
    if ($row['class'] === 'flagged' && $row['current']) {
        $tr->addClass('we-row-warning');
    }
    $table->addRow($tr);
}
$counts = $rf['counts'];
$root->addItem([new CTag('h2', true, _s('Neighbouring networks (%1$s)', $rf['total'])),
    new CTag('p', true, implode(' · ', array_map(static fn($k) => $classNames[$k].': '.$counts[$k], array_keys($counts)))
        .($rf['stale'] > 0 ? ' · '._s('%1$s heard only in stale observations', $rf['stale']) : '')
        .($rf['total'] > count($rf['neighbours']) ? ' · '._s('the %1$s strongest are listed', count($rf['neighbours'])) : '')),
    $table]);
