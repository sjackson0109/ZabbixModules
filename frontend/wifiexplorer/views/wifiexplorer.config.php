<?php
/**
 * Wi-Fi Explorer configuration (Super admins): the JSON document, every problem found when it last failed to save,
 * and the AP IDs and background images it can refer to.
 *
 * @var CView $this
 * @var array $data
 */
$page = (new CHtmlPage())->setTitle(_('Wi-Fi Explorer configuration'));
$root = (new CDiv())->addClass('we-explorer');
$root->addItem(new CLink(_('Back to Wi-Fi Explorer'), 'zabbix.php?action=wifiexplorer.view'));
if ($data['problems']) {
    $list = new CList();
    foreach ($data['problems'] as $problem) {
        $list->addItem($problem);
    }
    $root->addItem((new CDiv([new CTag('strong', true, _('Not saved:')), $list]))->addClass('msg-bad'));
}
$root->addItem((new CTag('p', true, _('Floors, AP positions, SSID-to-VLAN intent, event definitions and known external BSSIDs. This is declared intent and configuration: Wi-Fi Explorer compares observations against it and never infers it. Never put a password, PSK or RADIUS secret here.')))
    ->addClass('zx-note'));

$form = (new CForm('post'))->setAction((new CUrl('zabbix.php'))->setArgument('action', 'wifiexplorer.config.update')->getUrl())
    ->addVar(CCsrfTokenHelper::CSRF_TOKEN_NAME, CCsrfTokenHelper::get('wifiexplorer.config.update'));
$form->addItem((new CTextArea('config', $data['text']))->setId('we-config')->addClass('we-config-text')
    ->setAttribute('spellcheck', 'false')->setAttribute('aria-label', _('Configuration (JSON)')));
$form->addItem(new CSubmit('save', _('Save')));
$root->addItem($form);

$example = [
    'version'=>1,
    'floors'=>[['floor_id'=>'west-ground', 'site'=>'lab-west', 'building'=>'Main', 'name'=>'Ground floor', 'order'=>0,
        'imageid'=>'<background image ID>', 'width_m'=>60]],
    'placements'=>['ap-<24 hex>'=>['floor_id'=>'west-ground', 'x'=>0.25, 'y'=>0.4]],
    'ssids'=>[['ssid'=>'Event-WiFi', 'site'=>'lab-west', 'vlan'=>56, 'expect'=>'site', 'bands'=>['5', '6']]],
    'events'=>[['event_id'=>'conference', 'name'=>'Conference', 'site'=>'lab-west', 'ssid'=>'Event-WiFi',
        'starts'=>'2026-11-02T08:00:00Z', 'ends'=>'2026-11-02T18:00:00Z', 'min_aps'=>4, 'expected_clients'=>300,
        'clients_per_ap'=>60]],
    'known_bssids'=>[['bssid'=>'00:00:5e:00:53:f4', 'label'=>'Neighbouring office']]
];
$details = (new CTag('details', true))->addClass('zx-disclosure')->addClass('we-quality');
$details->addItem(new CTag('summary', true, _('Document format')));
$details->addItem(new CTag('p', true, _('x and y are fractions (0 to 1) of the plan\'s width and height. expect is site (every visible AP at the site), floors (the APs placed on the listed floors) or aps (the listed AP IDs). Events need an SSID declared for their site, and expected_clients needs clients_per_ap, the declared capacity of one AP.')));
$details->addItem((new CTag('pre', true, json_encode($example, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES)))->addClass('we-config-example'));
$root->addItem($details);

$aps = (new CTableInfo())->setHeader([_('AP'), _('Site'), _('AP ID'), _('Placed')])
    ->setNoDataMessage(_('No AP is visible.'));
foreach ($data['aps'] as $ap) {
    $aps->addRow([$ap['name'] ?? _('Unnamed access point'), $ap['site'], (new CSpan($ap['ap_uid']))->addClass('we-mono'),
        $ap['placed'] ? _('Yes') : _('No')]);
}
$images = (new CTableInfo())->setHeader([_('Background image'), _('Image ID')])
    ->setNoDataMessage(_('No background image. Upload floor plans under Administration → General → Images (type Background).'));
foreach ($data['images'] as $image) {
    $images->addRow([$image['name'], $image['imageid']]);
}
$root->addItem([new CTag('h2', true, _('Access points')), $aps, new CTag('h2', true, _('Floor-plan images')), $images]);
$page->addItem($root)->show();
