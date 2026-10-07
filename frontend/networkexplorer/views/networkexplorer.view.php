<?php
/** @var array $data Current user's permission-filtered application data. */
$page = (new CHtmlPage())->setTitle(_('Network Explorer'));
$root = (new CDiv())->addClass('ne-explorer');
if (isset($data['error'])) {
    $root->addItem((new CDiv(\Modules\NetworkExplorer\Services\Errors::message($data['error'])))->addClass('msg-bad'));
}
else {
    $form = (new CForm('get'))->setAction('zabbix.php');
    $form->addVar('action', 'networkexplorer.view');
    $form->addItem([new CLabel(_('Host ID'), 'hostid'), new CTextBox('hostid', $data['selected_hostid']),
        new CLabel(_('Management CIDR(s)'), 'management_cidr'),
        new CTextBox('management_cidr', $data['management_cidr']), new CSubmit('apply', _('Apply'))]);
    $root->addItem($form);
    $root->addItem(new CTag('p', true, _('Interfaces, LLDP, LAG, VLAN and STP reflect permitted current observations.')));
    $exports = new CDiv();
    $labels = ['inventory'=>_('Inventory CSV'), 'peers'=>_('Peers CSV'), 'addressing'=>_('Addressing CSV'),
        'degradation'=>_('Degradation CSV'), 'vlans'=>_('VLAN CSV'), 'stp'=>_('STP CSV'), 'quality'=>_('Quality CSV'),
        'findings'=>_('Findings CSV')];
    foreach (\Modules\NetworkExplorer\Services\ReportService::REPORTS as $report) {
        $params = ['action'=>'networkexplorer.export', 'report'=>$report, 'format'=>'csv'];
        if ($data['selected_hostid'] !== '') {
            $params['hostid'] = $data['selected_hostid'];
        }
        if ($data['management_cidr'] !== '') {
            $params['management_cidr'] = $data['management_cidr'];
        }
        $exports->addItem((new CLink($labels[$report] ?? $report, 'zabbix.php?'.http_build_query($params)))
            ->addClass('ne-export'));
    }
    $root->addItem($exports);
    $hosts = (new CTableInfo())->setHeader([_('Host'), _('Vendor / model'), _('Domain'), _('Management addresses')]);
    foreach ($data['hosts'] as $host) {
        $hosts->addRow([new CLink($host['name'], $host['dashboard_url']),
            ($host['vendor'] ?? '').' / '.($host['model'] ?? ''), $host['domain'] ?: _('Unknown'),
            implode(', ', $host['management_addresses'])]);
    }
    $root->addItem([new CTag('h2', true, _('Devices')), $hosts]);
    $ports = (new CTableInfo())->setHeader([_('Host'), _('Interface'), _('State'), _('Speed / intended'),
        _('Duplex'), _('Observation'), _('Peers')]);
    $names = array_column($data['hosts'], 'name', 'hostid');
    foreach ($data['interfaces'] as $interface) {
        $peerLinks = [];
        foreach ($interface['peers'] as $peer) {
            $peerLinks[] = $peer['dashboard_url'] !== null ? new CLink($peer['name'], $peer['dashboard_url']) : $peer['name'];
            $peerLinks[] = ' ';
        }
        $row = new CRow([$names[$interface['hostid']] ?? '',
            new CLink($interface['name'] ?? $interface['uid'], $interface['dashboard_url']),
            $interface['state'].' — '.$interface['reason'],
            (string) ($interface['speed_bps'] ?? _('Unknown')).' / '.(string) ($interface['expected_speed_bps'] ?? _('Unknown')).' bit/s',
            $interface['duplex'] ?? _('Unknown'), $interface['freshness'].' / '.($interface['observed_at'] ?? ''), $peerLinks]);
        if ($data['selected_uid'] === $interface['uid'] && $data['selected_hostid'] === $interface['hostid']) {
            $row->addClass('ne-selected-interface');
        }
        $ports->addRow($row);
    }
    $root->addItem([new CTag('h2', true, _('Interfaces')), $ports]);
    $quality = (new CTableInfo())->setHeader([_('Host'), _('Dataset'), _('Outcome'), _('Capability'), _('Freshness'), _('Observed')]);
    foreach ($data['quality'] as $row) {
        $quality->addRow([$names[$row['hostid']] ?? '', $row['dataset'], $row['status'], $row['capability'],
            $row['freshness'], $row['observed_at'] ?? _('Unknown')]);
    }
    $root->addItem([new CTag('h2', true, _('Collection quality')), $quality]);
    $findings = (new CTableInfo())->setHeader([_('Host'), _('Severity'), _('Finding'), _('Reason')]);
    foreach ($data['findings'] as $row) {
        $findings->addRow([$names[$row['hostid'] ?? ''] ?? '', $row['severity'], $row['title'] ?? $row['type'] ?? '',
            $row['reason'] ?? $row['message'] ?? '']);
    }
    $root->addItem([new CTag('h2', true, _('Findings')), $findings]);
}
$page->addItem($root)->show();
