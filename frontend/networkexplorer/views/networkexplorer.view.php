<?php
/**
 * Monitoring -> Network Explorer. The scope form reloads the page; the topology, selection detail, findings and
 * quality are drawn by the shared runtime (assets/js/runtime.js) from the current user's permission-filtered data.
 *
 * @var array $data
 */
use Modules\NetworkExplorer\Services\Errors;
use Modules\NetworkExplorer\Services\ReportService;

$request = $data['request'];
$options = $data['options'];
$page = (new CHtmlPage())->setTitle(_('Network Explorer'));
$root = (new CDiv())->addClass('ne-explorer');

$select = static function (string $name, string $label, array $values, string $selected): array {
    $field = (new CSelect($name))->setId('ne-scope-'.$name)->setFocusableElementId('ne-scope-'.$name.'-button')
        ->addOption(new CSelectOption($name === 'hostid' ? '0' : '', _('All')));
    foreach ($values as $value => $text) {
        $field->addOption(new CSelectOption((string) $value, (string) $text));
    }
    // A value no longer offered (a bookmark) is still shown, so the page states the scope it was asked for.
    if ($selected !== '' && !array_key_exists($selected, $values)) {
        $field->addOption(new CSelectOption($selected, $selected));
    }
    $field->setValue($selected === '' && $name === 'hostid' ? '0' : $selected);
    return [(new CDiv([new CLabel($label, 'ne-scope-'.$name.'-button'), $field]))->addClass('ne-scope-field')];
};
$sites = array_combine($options['sites'], $options['sites']) ?: [];
$domains = array_combine($options['domains'], $options['domains']) ?: [];
$devices = array_column($data['scope']['candidates'] ?? [], 'name', 'hostid');

$form = (new CForm('get'))->setAction('zabbix.php')->addClass('ne-scope')->setAttribute('aria-label', _('Scope'));
$form->addVar('action', 'networkexplorer.view');
$form->addItem($select('site', _('Site'), $sites, $request['site']));
$form->addItem($select('domain', _('Domain'), $domains, $request['domain']));
$form->addItem((new CDiv([new CLabel(_('Management subnet'), 'management_cidr'),
    (new CTextBox('management_cidr', $request['management_cidr']))->setAttribute('placeholder', _('All (for example 10.1.0.0/16)'))
        ->setWidth(ZBX_TEXTAREA_MEDIUM_WIDTH)]))->addClass('ne-scope-field'));
$form->addItem($select('hostid', _('Seed device'), $devices, $request['hostid']));
// The page keeps the view and VLAN in these as they change, so Apply keeps them; empty ones are not sent.
foreach (['view'=>$request['view'], 'vlan'=>(string) ($request['vlan'] ?? '')] as $name => $value) {
    $form->addItem((new CInput('hidden', $name, $value))->setAttribute('data-ne-state', $name)
        ->setEnabled($value !== ''));
}
$form->addItem(new CSubmit('apply', _('Apply')));
$root->addItem($form);
if ($options['truncated']) {
    $root->addItem((new CDiv(_('Only some site and domain values are listed. Type a narrower scope in the address.')))
        ->addClass('msg-warning'));
}

if (isset($data['error'])) {
    $root->addItem((new CDiv(Errors::message($data['error'])))->addClass('msg-bad'));
    $page->addItem($root)->show();
    return;
}

$summary = _n('%1$s permitted switch in scope.', '%1$s permitted switches in scope.', count($data['hosts']));
if ($request['hostid'] !== '') {
    $summary .= ' '._('Showing the seed device and its direct neighbours.');
}
$root->addItem(new CTag('p', true, $summary.' '
    ._('Interfaces, LLDP, LAG, VLAN and STP reflect permitted current observations. Host dashboards remain the place to investigate one switch.')));

$app = (new CDiv())->addClass('ne-widget')->addClass('ne-explorer-app')->setId('ne-explorer-app');
$root->addItem($app);

// Exports cover exactly the page's scope.
$scope = array_filter(['hostid'=>$request['hostid'], 'site'=>$request['site'], 'domain'=>$request['domain'],
    'management_cidr'=>$request['management_cidr']], static fn($value) => $value !== '');
$labels = ['inventory'=>_('Inventory'), 'peers'=>_('Peers'), 'addressing'=>_('Addressing'),
    'degradation'=>_('Degradation'), 'vlans'=>_('VLAN'), 'stp'=>_('STP'), 'quality'=>_('Quality'),
    'findings'=>_('Findings')];
$exports = (new CDiv())->addClass('ne-exports');
foreach (['csv'=>'CSV', 'json'=>'JSON'] as $format => $formatLabel) {
    $row = new CDiv(new CSpan($formatLabel.': '));
    foreach (ReportService::REPORTS as $report) {
        $params = ['action'=>'networkexplorer.export', 'report'=>$report, 'format'=>$format] + $scope;
        $row->addItem((new CLink($labels[$report] ?? $report, 'zabbix.php?'.http_build_query($params)))
            ->addClass('ne-export'));
    }
    $exports->addItem($row);
}

$tables = (new CTag('details', true))->addClass('ne-tables');
$tables->addItem(new CTag('summary', true, _('Exports and tables')));
$tables->addItem($exports);
$hosts = (new CTableInfo())->setHeader([_('Host'), _('Vendor / model'), _('Site'), _('Domain'),
    _('Management addresses')]);
foreach ($data['hosts'] as $host) {
    $hosts->addRow([new CLink($host['name'], $host['dashboard_url']),
        ($host['vendor'] ?? '').' / '.($host['model'] ?? ''), $host['site'] ?: _('Unknown'),
        $host['domain'] ?: _('Unknown'), implode(', ', $host['management_addresses'])]);
}
$tables->addItem([new CTag('h2', true, _('Devices')), $hosts]);
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
    if ($request['interface_uid'] === $interface['uid'] && $request['interface_hostid'] === $interface['hostid']) {
        $row->addClass('ne-selected-interface');
    }
    $ports->addRow($row);
}
$tables->addItem([new CTag('h2', true, _('Interfaces')), $ports]);
$root->addItem($tables);

$page->addItem($root)->show();

// Device strings reach the page only as JSON data, and the runtime renders them only via textContent.
$payload = array_diff_key($data, array_flip(['request', 'options']));
$json = static fn($value): string => json_encode($value, JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT
    | JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE);
(new CScriptTag('(function () {
    var start = function () {
        window.NEWidgetRuntime.mountExplorer(document.getElementById("ne-explorer-app"), '.$json($payload).', '
            .$json($request).');
    };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();'))->setOnDocumentReady(false)->show();
