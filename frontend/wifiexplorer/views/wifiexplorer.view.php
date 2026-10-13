<?php
/**
 * Monitoring -> Wi-Fi Explorer. Server-rendered from the current user's permission-filtered model: the scope, the
 * view tabs, and the selected view. Device strings reach the page only through Zabbix's escaping HTML classes.
 *
 * @var CView $this
 * @var array $data
 */
use Modules\WifiExplorer\Services\WifiErrors;

$request = $data['request'];
$view = $data['scope_view'] ?? 'overview';
$page = (new CHtmlPage())->setTitle(_('Wi-Fi Explorer'));
$root = (new CDiv())->addClass('we-explorer');

// Links keep the site; everything else is set per link. Only opaque IDs and fixed choices reach the address bar.
$link = static function (array $params) use ($request): string {
    return 'zabbix.php?'.http_build_query(['action'=>'wifiexplorer.view'] + array_filter($params + ['site'=>$request['site']],
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
$kind = static function (string $kind): CSpan {
    $names = ['observed'=>_('Observed'), 'interpolated'=>_('Interpolated'), 'configured'=>_('Configured'),
        'inferred'=>_('Inferred'), 'declared'=>_('Declared intent'), 'estimated'=>_('Estimated'),
        'not_collected'=>_('Not collected')];
    return (new CSpan($names[$kind] ?? $kind))->addClass('we-kind')->addClass('we-kind-'.$kind);
};

// Scope: a site narrows the view; changing it drops selections, which belong to one scope.
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
$form->addVar('view', $view);
$form->addItem((new CDiv([new CLabel(_('Site'), 'we-site-button'), $select]))->addClass('we-scope-field'));
$form->addItem((new CDiv([new CLabel(_('Search'), 'we-q'), (new CTextBox('q', $request['q']))->setId('we-q')
    ->setAttribute('maxlength', 64)->setAttribute('placeholder', _('AP, model, SSID, BSSID, channel, client'))
    ->setWidth(ZBX_TEXTAREA_STANDARD_WIDTH)]))->addClass('we-scope-field'));
$form->addItem(new CSubmit('apply', _('Apply')));
if ($data['can_configure'] ?? false) {
    $form->addItem((new CLink(_('Configure'), 'zabbix.php?action=wifiexplorer.config.edit'))->addClass('we-configure'));
}
$root->addItem($form);

if (isset($data['error'])) {
    $root->addItem((new CDiv(WifiErrors::message($data['error'])))->addClass('msg-bad'));
    $page->addItem($root)->show();
    return;
}

$tabs = (new CList())->addClass('we-tabs')->setAttribute('role', 'navigation');
$tabNames = ['overview'=>_('Overview'), 'floors'=>_('Floor plans'), 'rf'=>_('RF neighbours'), 'ssids'=>_('SSIDs'), 'paths'=>_('VLAN paths')];
foreach ($tabNames as $key => $name) {
    $item = new CLink($name, $link(['view'=>$key === 'overview' ? '' : $key, 'q'=>$request['q']]));
    if ($key === $view) {
        $item->setAttribute('aria-current', 'page');
    }
    $tabs->addItem((new CListItem($item))->addClass($key === $view ? 'we-tab-active' : 'we-tab'));
}
$root->addItem($tabs);

if ($data['config_invalid'] ?? false) {
    $root->addItem((new CDiv(_('The stored Wi-Fi configuration does not validate, so floors, placements and intent are ignored. A Super admin can correct it under Configure.')))
        ->addClass('msg-warning'));
}

if ($data['owners'] === []) {
    $root->addItem((new CDiv([
        new CTag('p', true, _('No Wi-Fi data source is visible to you in this scope.')),
        new CTag('p', true, _('Link the "Wi-Fi Explorer - Aruba Instant VC by SNMP" template to one host per Aruba Instant cluster, pointed at the cluster\'s virtual controller address, and check that your user group can read that host.'))
    ]))->addClass('we-empty'));
    $page->addItem($root)->show();
    return;
}

$byUid = array_column($data['aps'], null, 'ap_uid');
$urls = array_column($data['owners'], 'dashboard_url', 'hostid');
$apName = static fn(?string $uid): string => $uid !== null && isset($byUid[$uid])
    ? ($byUid[$uid]['name'] ?? _('Unnamed access point')) : _('Unknown AP');

include __DIR__.'/partials/'.$view.'.php';

$page->addItem($root)->show();
