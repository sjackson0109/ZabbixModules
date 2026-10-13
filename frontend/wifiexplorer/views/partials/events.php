<?php
/**
 * Event readiness: each declared event with a checklist from current observations and the event's own declaration.
 *
 * @var array $data
 * @var CDiv $root
 */
$root->addItem((new CTag('p', true, _('Ready means every check passes from current observations. Unknown means nothing fails but something cannot be shown. Capacity is the declared clients per AP, not a measurement. Credentials are not validated.')))
    ->addClass('we-note'));
$statusNames = ['ready'=>_('Ready'), 'not_ready'=>_('Not ready'), 'unknown'=>_('Unknown')];
$timings = ['upcoming'=>_('Upcoming'), 'in_progress'=>_('In progress'), 'ended'=>_('Ended')];
$table = (new CTableInfo())->setHeader([_('Event'), _('Site'), _('SSID'), _('Starts'), _('Ends'), _('When'), _('Readiness')])
    ->setNoDataMessage(_('No event is declared for the visible sites. A Super admin can declare one under Configure.'));
$selected = null;
foreach ($data['events'] as $event) {
    if ($event['event_id'] === $request['event']) {
        $selected = $event;
    }
    $row = new CRow([new CLink($event['name'], $link(['view'=>'events', 'event'=>$event['event_id']])), $event['site'],
        $event['ssid_uid'] !== null ? new CLink($event['ssid'], $link(['view'=>'ssids', 'ssid'=>$event['ssid_uid']])) : $event['ssid'],
        $event['starts'], $event['ends'], $timings[$event['timing']],
        (new CSpan($statusNames[$event['status']]))->addClass('we-ready-'.$event['status'])]);
    if ($event['event_id'] === $request['event']) {
        $row->addClass('we-selected');
    }
    $table->addRow($row);
}
$root->addItem([new CTag('h2', true, _('Events')), $table]);

if ($request['event'] !== '' && $selected === null) {
    $root->addItem((new CDiv(_('The selected event is not declared for a visible site.')))->addClass('msg-warning'));
}
if ($selected === null) {
    return;
}
$checkNames = ['ssid_enabled'=>_('SSID enabled'), 'aps_expected'=>_('APs expected'), 'aps_up'=>_('APs up'),
    'broadcasting'=>_('SSID on air'), 'vlan_paths'=>_('VLAN paths'), 'capacity'=>_('Capacity'),
    'utilisation'=>_('Channel utilisation'), 'credentials'=>_('Credentials')];
$results = ['pass'=>_('Pass'), 'fail'=>_('Fail'), 'unknown'=>_('Unknown'), 'warn'=>_('Warning'), 'not_checked'=>_('Not checked')];
$detail = (new CDiv())->addClass('we-detail');
$detail->addItem(new CTag('h2', true, [$selected['name'], ' ',
    (new CSpan($statusNames[$selected['status']]))->addClass('we-ready-'.$selected['status'])]));
$facts = [_s('%1$s on %2$s, %3$s to %4$s.', $selected['ssid'], $selected['site'], $selected['starts'], $selected['ends'])];
if ($selected['floors']) {
    $names = array_column($data['floors']['floors'], 'name', 'floor_id');
    $facts[] = _s('Floors: %1$s.', implode(', ', array_map(static fn($f) => $names[$f] ?? $f, $selected['floors'])));
}
if ($selected['min_aps'] !== null) {
    $facts[] = _s('At least %1$s APs.', $selected['min_aps']);
}
$detail->addItem(new CTag('p', true, implode(' ', $facts)));
$checks = (new CTableInfo())->setHeader([_('Check'), _('Result'), _('Detail'), _('Basis')]);
foreach ($selected['checks'] as $check) {
    $checks->addRow([$checkNames[$check['check']] ?? $check['check'],
        (new CSpan($results[$check['status']]))->addClass('we-check-'.$check['status']), $check['detail'], $kind($check['kind'])]);
}
$detail->addItem($checks);
$aps = [];
foreach ($selected['aps'] as $apUid) {
    $aps[] = new CLink($apName($apUid), $link(['ap'=>$apUid]));
    $aps[] = ', ';
}
array_pop($aps);
$detail->addItem([new CTag('h3', true, _('Access points serving the event')), new CTag('p', true, $aps ?: _('None'))]);
$root->addItem($detail);
