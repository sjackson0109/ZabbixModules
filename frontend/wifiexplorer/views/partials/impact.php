<?php
/**
 * Blast radius: choose a visible switch, or one of its ports, and see which APs, SSIDs, VLANs, floors and clients
 * depend on it, from the uplinks and spanning-tree paths. Nothing is predicted beyond what the model shows.
 *
 * @var array $data
 * @var CDiv $root
 */
$root->addItem($about(_('What depends on a switch or port, from each AP\'s uplink and its spanning-tree path to the root.'),
    _('"Reroute possible" means a switch below the failure has an STP alternate port that is up; spanning tree may reconverge through it, which is not simulated. Client numbers are the clients associated now, an estimate of who is affected: some may roam to a neighbouring AP. PoE is not collected, so whether an AP also loses power is not shown.')));

if (!$data['wired']['available']) {
    $root->addItem((new CDiv(\Modules\WifiExplorer\Services\WifiErrors::wired($data['wired']['reason'])))->addClass('msg-warning'));
    return;
}

$hostSelect = (new CSelect('fail_host'))->setId('we-fail-host')->setFocusableElementId('we-fail-host-button')
    ->addOption(new CSelectOption('', _('Select a switch')));
foreach ($data['wired']['hosts'] ?? [] as $host) {
    $hostSelect->addOption(new CSelectOption($host['hostid'], $host['name']));
}
$hostSelect->setValue($request['fail_host']);
$interfaceSelect = (new CSelect('fail_if'))->setId('we-fail-if')->setFocusableElementId('we-fail-if-button')
    ->addOption(new CSelectOption('', _('The whole switch')));
$interfaces = $data['wired']['interfaces'] ?? [];
usort($interfaces, static fn($a, $b) => strnatcasecmp($a['name'], $b['name']));
foreach ($interfaces as $interface) {
    $interfaceSelect->addOption(new CSelectOption($interface['uid'], $interface['name']));
}
$interfaceSelect->setValue($request['fail_if']);
$form = (new CForm('get'))->setAction('zabbix.php')->addClass('we-scope');
$form->addVar('action', 'wifiexplorer.view');
$form->addVar('view', 'impact');
$form->addVar('site', $request['site']);
$form->addItem((new CDiv([new CLabel(_('If this switch fails'), 'we-fail-host-button'), $hostSelect]))->addClass('we-scope-field'));
$form->addItem((new CDiv([new CLabel(_('or this port'), 'we-fail-if-button'), $interfaceSelect]))->addClass('we-scope-field'));
$form->addItem(new CSubmit('assess', _('Assess')));
$root->addItem($form);
if ($request['fail_host'] !== '' && $request['fail_if'] === '' && $interfaces) {
    $root->addItem((new CTag('p', true, _('Assessing the whole switch. Choose a port and Assess again to narrow it.')))->addClass('we-muted'));
}

$impact = $data['impact'];
if ($impact === null) {
    // Before a switch is chosen: the switches whose failure would cost the most, each one link from its assessment.
    $ranking = (new CTableInfo())->setHeader([_('Switch'), _('APs that lose service'), _('Degraded'), _('May reroute'),
        _('Clients on those APs now')])->setNoDataMessage(_('No AP\'s uplink or path to the root is known, so no switch can be ranked.'));
    foreach ($data['wired']['ranking'] ?? [] as $row) {
        $ranking->addRow([new CLink($row['name'], $link(['view'=>'impact', 'fail_host'=>$row['hostid']])), $row['lost'],
            $row['degraded'], $row['reroute_possible'],
            [$row['clients'], $row['aps_without_count'] ? ' '._s('(and %1$s AP(s) without a current count)', $row['aps_without_count']) : '']]);
    }
    $root->addItem([new CTag('h2', true, _('Switches with the most depending on them')),
        (new CTag('p', true, _('If each switch failed on its own. Choose one to see the APs, SSIDs, VLANs and floors behind it.')))
            ->addClass('we-muted'), $ranking]);
    return;
}
if ($impact['status'] !== 'ok') {
    $root->addItem((new CDiv($impact['status'] === 'interface_not_visible'
        ? _('That port is not visible on the selected switch.')
        : _('That switch is not part of this site\'s visible wired network.')))->addClass('msg-warning'));
    return;
}
$target = $impact['target'];
$counts = $impact['counts'];
$summary = (new CDiv())->addClass('we-detail');
$summary->addItem(new CTag('h2', true, _s('If %1$s fails', $target['name'].($target['interface_name'] !== null
    ? ' '.$target['interface_name'] : ''))));
$lines = [];
$lines[] = _s('%1$s AP(s) lose service, %2$s degraded, %3$s may reroute, %4$s cannot be assessed, %5$s unaffected.',
    $counts['lost'], $counts['degraded'], $counts['reroute_possible'], $counts['cannot_assess'], $impact['unaffected']);
if ($target['lag_member_of'] !== null) {
    $lines[] = _s('This port is a member of %1$s; APs keep service while another member is up.', $target['lag_member_of']);
}
if ($target['is_root'] && $target['interface_uid'] === null) {
    $lines[] = _('This switch is the spanning-tree root bridge. Another root would be elected; the resulting paths are not predicted.');
}
$floorNames = array_column($data['floors']['floors'], 'name', 'floor_id');
$floorText = [];
foreach ($impact['floors'] as $floor => $count) {
    $floorText[] = ($floorNames[$floor] ?? $floor).' ('.$count.')';
}
$lines[] = _s('VLANs carrying the lost APs\' SSIDs: %1$s.', $impact['vlans'] ? implode(', ', $impact['vlans']) : _('none'));
$lines[] = _s('Floors: %1$s.', $floorText ? implode(', ', $floorText) : _('none of the lost APs is placed'));
foreach ($lines as $line) {
    $summary->addItem(new CTag('p', true, $line));
}
$summary->addItem(new CTag('p', true, [_s('Clients associated now with the lost APs: %1$s', $impact['clients']['estimated']),
    $impact['clients']['aps_without_count'] ? ' '._s('(and %1$s AP(s) without a current count)', $impact['clients']['aps_without_count']) : '',
    ' ', $kind('estimated')]));
$root->addItem($summary);

$ssidTable = (new CTableInfo())->setHeader([_('SSID'), _('Broadcasting APs'), _('Lost'), _('At risk'), _('VLAN')])
    ->setNoDataMessage(_('No broadcasting SSID depends on this element.'));
foreach ($impact['ssids'] as $row) {
    $tr = new CRow([new CLink($row['name'], $link(['view'=>'ssids', 'ssid'=>$row['ssid_uid']])), $row['broadcasting'],
        $row['lost'].($row['all_lost'] ? ' '._('(all)') : ''), $row['at_risk'], implode(', ', $row['vlans']) ?: '—']);
    if ($row['all_lost']) {
        $tr->addClass('we-row-warning');
    }
    $ssidTable->addRow($tr);
}
$root->addItem([new CTag('h2', true, _('SSIDs')), $ssidTable]);

$impacts = ['lost'=>_('Loses service'), 'degraded'=>_('Degraded'), 'reroute_possible'=>_('Reroute possible'),
    'cannot_assess'=>_('Cannot assess')];
$why = ['ap_switch'=>_('its own switch'), 'ap_port'=>_('its own port'), 'upstream_switch'=>_('a switch on its path'),
    'upstream_port'=>_('a port on its path'), 'lag_member'=>_('a LAG member on its path; other members are up'),
    'lag_state_unknown'=>_('a LAG member on its path; the other members\' state is not current'),
    'uplink_unknown'=>_('its uplink is unknown'), 'path_partial'=>_('its path stops before the root'),
    'path_unknown'=>_('its path is unknown')];
$apTable = (new CTableInfo())->setHeader([_('Access point'), _('Impact'), _('Why'), _('Clients now'), _('STP alternates')])
    ->setNoDataMessage(_('No visible AP depends on this element.'));
foreach ($impact['aps'] as $row) {
    $alternates = [];
    foreach ($row['alternates'] as $alternate) {
        $alternates[] = $alternate['switch_name'].' '.$alternate['interface_name']
            .($alternate['carried'] !== null ? ' ('._s('carries %1$s', $alternate['carried']).')' : '');
    }
    $apTable->addRow([new CLink($apName($row['ap_uid']), $link(['ap'=>$row['ap_uid']])),
        $toned($impacts[$row['impact']], $row['impact']),
        $why[$row['reason']] ?? $row['reason'], $row['clients'] ?? _('Unknown'), $alternates ? implode('; ', $alternates) : '—']);
}
$root->addItem([new CTag('h2', true, _('Access points')), $apTable]);
