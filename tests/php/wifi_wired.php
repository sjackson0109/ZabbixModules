<?php
declare(strict_types=1);

require_once __DIR__.'/wifi_lab.php';

use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

/** Phase C: SSID inventory and intent, and AP-to-switch uplinks from Network Explorer's model. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $build = static function (array $more, string $ap = '', array $omit = [], ?array $config = null) {
        return (new WifiService(WifiLab::gateway($omit), WifiLab::now(), $config ?? WifiLab::config()))
            ->build(WifiScope::create('lab-west', $ap, $more));
    };
    $findings = static fn(array $model, string $rule): array => array_values(array_filter($model['findings'],
        static fn($f) => $f['rule'] === $rule));
    $ssid = static fn(array $model, string $name): ?array => array_column($model['ssids'], null, 'name')[$name] ?? null;
    $aps = static fn(array $model): array => array_column($model['aps'], null, 'ap_uid');

    // SSIDs: observed from the cluster, VLAN from declared intent only.
    $model = $build(['view'=>'ssids']);
    $corp = $ssid($model, 'Lab-Corp');
    $assert($corp !== null && $corp['enabled'] === true && $corp['clients'] === 5, 'Lab-Corp is observed enabled with 5 clients.');
    $assert($corp['vlans'] === ['lab-west'=>49], 'Its VLAN is the declared one.');
    $legacy = $ssid($model, 'Lab-Legacy');
    $assert($legacy['enabled'] === false && $legacy['vlans'] === [] && !$legacy['declared'],
        'An undeclared SSID has no VLAN, never a guessed one.');
    $assert($ssid($model, 'Lab-Guest')['hidden'] === true, 'The hidden flag is kept.');
    $assert(count($findings($model, 'wifi_ssid_missing')) === 1
        && $findings($model, 'wifi_ssid_missing')[0]['object_id'] === $ssid($model, 'Lab-Expected')['ssid_uid'],
        'A declared SSID no cluster has is a warning.');
    $assert($findings($model, 'wifi_ssid_vlan_undeclared') === [],
        'Every enabled lab SSID is declared, so none lacks a VLAN.');

    // Broadcasting is inferred per expected AP, never observed.
    $event = array_column($ssid($model, 'Lab-Event')['expected'], null, 'ap_uid');
    $assert($event[WifiLab::apUid(1)]['status'] === 'broadcasting' && $event[WifiLab::apUid(1)]['kind'] === 'inferred',
        'An up AP with a 5 GHz radio up broadcasts the 5/6 GHz SSID (inferred).');
    $assert($event[WifiLab::apUid(3)]['reason'] === 'ap_down', 'A down AP does not broadcast.');
    $guest = $ssid($model, 'Lab-Guest');
    $assert(count($guest['expected']) === 3, 'Lab-Guest is expected on the three APs placed on its floor only.');
    $coverage = $findings($model, 'wifi_ssid_coverage_gap');
    $assert(count($coverage) === 2 && $coverage[0]['confidence'] === 'inferred', 'Coverage gaps are inferred warnings.');

    // An SSID observed without intent: its VLAN is reported as undeclared.
    $config = WifiLab::config();
    $config['ssids'] = array_values(array_filter($config['ssids'], static fn($s) => $s['ssid'] !== 'Lab-Corp'));
    $config['events'] = [];
    $undeclared = $build(['view'=>'ssids'], '', [], $config);
    $assert(count($findings($undeclared, 'wifi_ssid_vlan_undeclared')) === 1, 'An enabled SSID without intent says its VLAN is unknown.');
    $corp = $ssid($undeclared, 'Lab-Corp');
    $assert(count($corp['expected']) === 6 && $corp['expected'][0]['basis'] === 'observed_cluster',
        'Without intent, every AP of a cluster that enables it is expected, on observed grounds.');

    // Uplinks: switch LLDP by chassis MAC, AP LLDP resolved with Network Explorer's resolver.
    $byUid = $aps($model);
    $assert($model['wired']['available'] && $model['wired']['switches'] === 3, 'The site\'s switches are read.');
    $ap1 = $byUid[WifiLab::apUid(1)]['uplink'];
    $assert($ap1['state'] === 'confirmed' && $ap1['switch_name'] === 'sw-wifi-access-01' && $ap1['interface_name'] === 'Gi1/0/1',
        'lab-ap-01 is confirmed on sw-wifi-access-01 Gi1/0/1 by both sides.');
    $assert($ap1['basis'] === 'chassis_mac' && $ap1['vlan']['carried'] === '49,56-57', 'Its port VLANs come from Network Explorer.');
    $ap4 = $byUid[WifiLab::apUid(4)]['uplink'];
    $assert($ap4['state'] === 'switch_only' && $ap4['switch_name'] === 'sw-wifi-access-02', 'lab-ap-04 is seen by its switch only.');
    $assert($byUid[WifiLab::apUid(6)]['uplink']['state'] === 'unresolved', 'lab-ap-06 has no uplink evidence.');
    $unresolved = $findings($model, 'wifi_uplink_unresolved');
    $assert(count($unresolved) === 1 && $unresolved[0]['object_id'] === WifiLab::apUid(6),
        'Only the up AP without evidence raises a finding; the down AP does not.');
    $owners = array_column($model['owners'], null, 'hostid');
    $assert($owners['20']['observes_ap'] === WifiLab::apUid(1) && $owners['10']['observes_ap'] === null,
        'The per-AP host observes lab-ap-01; the virtual controller observes none.');

    // Permissions: a switch the viewer cannot read contributes nothing.
    $hidden = $aps($build(['view'=>'ssids'], '', ['31']));
    $assert($hidden[WifiLab::apUid(1)]['uplink']['state'] === 'unresolved'
        && $hidden[WifiLab::apUid(4)]['uplink']['state'] === 'switch_only',
        'Without sw-wifi-access-01 its APs are unresolved; the other switch still resolves its own.');

    // A conflict: the AP's LLDP names a port that its switch does not report it on.
    $gateway = WifiLab::gateway();
    foreach ($gateway->itemRows as $item) {
        if ($item['hostid'] === '20' && $item['key_'] === 'ne.lldp.snapshot') {
            $envelope = json_decode($gateway->values[$item['itemid']][0]['value'], true);
            $envelope['data'][0]['remote_port_id'] = ['subtype'=>5, 'value'=>'Gi1/0/2'];
            $gateway->values[$item['itemid']] = [['value'=>json_encode($envelope)]];
        }
    }
    $moved = (new WifiService($gateway, WifiLab::now(), WifiLab::config()))->build(WifiScope::create('lab-west', '', ['view'=>'ssids']));
    $assert($aps($moved)[WifiLab::apUid(1)]['uplink']['state'] !== 'confirmed', 'A disagreeing AP-side port is never confirmed.');

    // An AP host linked to the whole Network Explorer template is drawn as a host and still gives its side.
    $full = WifiLab::gateway();
    WifiLab::feedNetwork($full, '20', 'aruba-instant-ap-01.snmprec', ['ne.raw.system', 'ne.raw.if.inventory', 'ne.raw.if.state']);
    $drawn = (new WifiService($full, WifiLab::now(), WifiLab::config()))->build(WifiScope::create('lab-west', '', ['view'=>'ssids']));
    $assert($aps($drawn)[WifiLab::apUid(1)]['uplink']['state'] === 'confirmed',
        'An AP host that is also a Network Explorer host still confirms its uplink.');

    // Uplinks need a site and are not computed for views that do not use them.
    $assert($build(['view'=>'floors'])['wired']['reason'] === 'not_requested', 'The floor view reads no switch data.');
    $overview = $build([]);
    $assert($overview['wired']['available'] && $findings($overview, 'wifi_uplink_unresolved') !== []
        && array_column($overview['findings'], 'rule') === array_column($build([], WifiLab::apUid(1))['findings'], 'rule'),
        'The overview carries the uplink findings, and selecting an AP does not change them.');
    $all = (new WifiService(WifiLab::gateway(), WifiLab::now(), WifiLab::config()))->build(WifiScope::create('', '', ['view'=>'ssids']));
    $assert($all['wired']['reason'] === 'site_required', 'Without a site the wired model is not read.');

    echo "Wi-Fi SSID and uplink checks passed ({$checks} checks).\n";
})();
