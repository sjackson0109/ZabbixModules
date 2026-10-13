<?php
/**
 * VLAN service paths: per SSID with a declared VLAN, AP by AP, whether the VLAN reaches the AP's switch port and
 * continues to the spanning-tree root, naming the first failing hop.
 *
 * @var array $data
 * @var CDiv $root
 */
$pathReasons = [
    'uplink_unresolved'=>_('AP uplink unresolved'), 'uplink_conflicting'=>_('AP and switch disagree about the uplink'),
    'uplink_ambiguous'=>_('AP seen on several switch ports'), 'stp_not_collected'=>_('spanning tree not collected'),
    'stp_no_bridge'=>_('no spanning-tree bridge reported'), 'stp_stale'=>_('spanning-tree data stale'),
    'stp_root_disagreement'=>_('switches disagree about the root bridge'), 'no_root_port'=>_('no root port reported'),
    'upstream_link_unresolved'=>_('the root port\'s link is not resolved'),
    'upstream_link_ambiguous'=>_('the root port leads to more than one switch'),
    'upstream_not_visible'=>_('the upstream switch is not visible'), 'loop'=>_('the walk returned to a switch'),
    'too_many_hops'=>_('more hops than checked'), 'mstp_instance'=>_('the VLAN is mapped to an MSTP instance other than the CIST'),
    'interface_not_visible'=>_('port not visible'), 'port_state_stale'=>_('port state stale'),
    'port_state_unknown'=>_('port state unknown'), 'port_down'=>_('port down'),
    'vlan_not_collected'=>_('VLAN membership not collected'), 'vlan_membership_unknown'=>_('VLAN membership unknown'),
    'vlan_data_stale'=>_('VLAN data stale'), 'vlan_not_on_ap_port'=>_('VLAN not on the AP\'s port'),
    'vlan_not_carried'=>_('VLAN not carried'), 'stp_blocking'=>_('spanning tree blocks the port')
];
$pathStates = ['complete'=>_('Complete'), 'failed'=>_('Failed'), 'partial'=>_('Partial'), 'unknown'=>_('Unknown')];
$roles = ['access'=>_('AP port'), 'root_port'=>_('root port'), 'designated'=>_('upstream')];

$root->addItem((new CTag('p', true, _('A path is complete only when every port from the AP\'s switch port to the spanning-tree root bridge is up, carries the SSID\'s declared VLAN and is not blocked, from current observations. It follows the instance-0 (CST/CIST) root ports in Network Explorer\'s model, never cable geometry. The VLAN\'s gateway (Layer 3) is not checked.')))
    ->addClass('we-note'));

if (!$data['wired']['available']) {
    $root->addItem((new CDiv(\Modules\WifiExplorer\Services\WifiErrors::wired($data['wired']['reason'])))->addClass('msg-warning'));
    return;
}

$summary = (new CTableInfo())->setHeader([_('SSID'), _('VLAN'), _('Complete'), _('Failed'), _('Partial'), _('Unknown')])
    ->setNoDataMessage(_('No SSID with a declared VLAN is expected on a visible AP. Declare SSID intent under Configure.'));
$selected = $data['paths'][$request['ssid']] ?? null;
foreach ($data['paths'] as $uid => $path) {
    $vlans = array_unique(array_column($path['results'], 'vlan'));
    $row = new CRow([new CLink($path['name'], $link(['view'=>'paths', 'ssid'=>$uid])), implode(', ', $vlans),
        $path['counts']['complete'], (new CSpan($path['counts']['failed']))->addClass($path['counts']['failed'] ? 'we-path-failed' : ''),
        $path['counts']['partial'], $path['counts']['unknown']]);
    if ($uid === $request['ssid']) {
        $row->addClass('we-selected');
    }
    $summary->addRow($row);
}
$root->addItem([new CTag('h2', true, _('Service paths by SSID')), $summary]);

if ($selected === null) {
    $root->addItem((new CTag('p', true, _('Select an SSID to see each AP\'s path hop by hop.')))->addClass('we-muted'));
    return;
}
$table = (new CTableInfo())->setHeader([_('Access point'), _('VLAN'), _('Result'), _('Why'), _('Path, AP to root')]);
$results = $selected['results'];
uasort($results, static fn($a, $b) => [array_search($a['status'], ['failed', 'unknown', 'partial', 'complete'], true),
    $apName($a['ap_uid'])] <=> [array_search($b['status'], ['failed', 'unknown', 'partial', 'complete'], true), $apName($b['ap_uid'])]);
foreach ($results as $result) {
    $hops = (new CDiv())->addClass('we-hops');
    foreach ($result['hops'] as $index => $hop) {
        if ($index > 0) {
            $hops->addItem($hop['role'] === 'designated' ? '⇢' : '·');
        }
        $label = ($hop['switch_name'] ?? '?').' '.($hop['interface_name'] ?? $hop['interface_uid']);
        $item = (new CSpan($hop['explorer_url'] !== null ? new CLink($label, $hop['explorer_url']) : $label))
            ->addClass('we-hop')->addClass('we-hop-'.$hop['status'])
            ->setTitle($roles[$hop['role']].($hop['tagging'] !== null ? ', '.$hop['tagging'] : '')
                .($hop['reason'] !== null ? ': '.($pathReasons[$hop['reason']] ?? $hop['reason']) : '')
                .($hop['lag_members'] ? ', '._s('LAG of %1$s', count($hop['lag_members'])) : ''));
        $hops->addItem($item);
    }
    if ($result['chain_status'] === 'complete' && $result['hops']) {
        $hops->addItem((new CSpan(_('root bridge')))->addClass('we-muted'));
    }
    $why = $result['reason'] !== null ? ($pathReasons[$result['reason']] ?? $result['reason']) : '';
    if ($result['status'] === 'failed') {
        $hop = $result['hops'][$result['failed_hop']];
        $why = _s('Hop %1$s, %2$s %3$s: %4$s', $result['failed_hop'] + 1, $hop['switch_name'] ?? '?',
            $hop['interface_name'] ?? '?', $why).($result['uncertain_before'] ? ' '._('(an earlier hop is also unproven)') : '');
    }
    if (in_array('mstp_cist_only', $result['caveats'], true)) {
        $why .= ($why !== '' ? '; ' : '')._('MSTP: checked along the CIST');
    }
    $table->addRow([new CLink($apName($result['ap_uid']), $link(['ap'=>$result['ap_uid']])), $result['vlan'],
        (new CSpan($pathStates[$result['status']]))->addClass('we-path-'.$result['status']), $why, $hops]);
}
$root->addItem([new CTag('h2', true, _s('%1$s: path per access point', $selected['name'])), $table]);
