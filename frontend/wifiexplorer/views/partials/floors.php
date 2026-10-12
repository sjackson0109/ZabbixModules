<?php
/**
 * Floor plans: the floors of the visible sites, the selected floor with its APs at their configured positions, the
 * chosen overlay and its evidence label, and the APs with no placement (never silently omitted).
 *
 * @var array $data
 * @var CDiv $root
 */
$floors = $data['floors'];
$selected = $floors['selected_floor'];

if ($floors['floors'] === []) {
    $root->addItem((new CDiv([
        new CTag('p', true, _('No floor plan is configured for the visible sites.')),
        new CTag('p', true, ($data['can_configure'] ?? false)
            ? _('Upload each floor plan as a background image (Administration → General → Images), then add the floor under Configure and place the APs on it.')
            : _('A Super admin adds floors and places APs under Wi-Fi Explorer → Configure.'))
    ]))->addClass('we-empty'));
}
else {
    $list = (new CTableInfo())->setHeader([_('Site'), _('Building'), _('Floor'), _('APs placed'), _('Scale')]);
    foreach ($floors['floors'] as $floor) {
        $row = new CRow([$floor['site'], $floor['building'] !== '' ? $floor['building'] : '—',
            new CLink($floor['name'], $link(['view'=>'floors', 'floor'=>$floor['floor_id'], 'overlay'=>$request['overlay']])),
            $floor['ap_count'], $floor['width_m'] !== null ? _s('%1$s m wide', $floor['width_m']) : _('Not set')]);
        if ($selected !== null && $floor['floor_id'] === $selected['floor_id']) {
            $row->addClass('we-selected');
        }
        $list->addRow($row);
    }
    $root->addItem([new CTag('h2', true, _('Floors')), $list]);
}
if ($floors['floor_missing']) {
    $root->addItem((new CDiv(_('The selected floor is not configured for the sites visible to you.')))->addClass('msg-warning'));
}

if ($selected !== null) {
    $overlayNames = ['status'=>_('AP status'), 'band'=>_('Bands'), 'channel'=>_('Channels'),
        'utilisation'=>_('Channel utilisation'), 'clients'=>_('Client density'), 'neighbours'=>_('Neighbour networks'),
        'retries'=>_('Retries and errors')];
    $bar = (new CDiv())->addClass('we-overlays');
    $bar->addItem((new CSpan(_('Overlay').':'))->addClass('we-overlay-label'));
    foreach ($floors['overlays'] as $overlay) {
        $item = new CLink($overlayNames[$overlay], $link(['view'=>'floors', 'floor'=>$selected['floor_id'],
            'overlay'=>$overlay, 'band'=>$selected['band'], 'ap'=>$data['selected_ap']]));
        $bar->addItem($overlay === $selected['overlay'] ? (new CSpan($overlayNames[$overlay]))->addClass('we-overlay-active') : $item);
    }
    $bar->addItem((new CSpan(_('Band').':'))->addClass('we-overlay-label'));
    foreach (['', '2.4', '5', '6'] as $band) {
        $name = $band === '' ? _('All') : $band.' GHz';
        $bar->addItem($band === $selected['band'] ? (new CSpan($name))->addClass('we-overlay-active')
            : new CLink($name, $link(['view'=>'floors', 'floor'=>$selected['floor_id'], 'overlay'=>$selected['overlay'],
                'band'=>$band, 'ap'=>$data['selected_ap']])));
    }
    $legend = $selected['legend'];
    $root->addItem([new CTag('h2', true, $selected['site'].' · '.($selected['building'] !== '' ? $selected['building'].' · ' : '')
        .$selected['name']), $bar,
        (new CDiv([$kind('configured'), ' '._('AP positions.').' ', $kind($legend['kind']), ' '.$legend['text']]))
            ->addClass('we-legend')]);

    $width = 1000;
    $height = (int) round(1000 * $selected['aspect_used']);
    $scale = static fn(float $v): string => (string) round($v * 1000, 1);
    $svg = (new CTag('svg', true))->addClass('we-floor')->setAttribute('viewBox', '0 0 '.$width.' '.$height)
        ->setAttribute('role', 'img')->setAttribute('aria-label', _s('Floor plan %1$s with %2$s APs', $selected['name'],
            count($selected['markers'])))
        ->setAttribute('data-floor', $selected['floor_id'])->setAttribute('data-aspect', (string) $selected['aspect_used']);
    $svg->addItem((new CTag('rect', true))->addClass('we-floor-paper')->setAttribute('width', (string) $width)
        ->setAttribute('height', (string) $height));
    if ($selected['imageid'] !== null) {
        $svg->addItem((new CTag('image', true))->setAttribute('href', 'imgstore.php?iconid='.$selected['imageid'])
            ->setAttribute('width', (string) $width)->setAttribute('height', (string) $height)
            ->setAttribute('preserveAspectRatio', 'none'));
    }
    if ($selected['field'] !== null) {
        $field = $selected['field'];
        $group = (new CTag('g', true))->addClass('we-field')->addClass('we-field-'.$selected['overlay']);
        foreach ($field['cells'] as [$c, $r, $v]) {
            $group->addItem((new CTag('rect', true))->setAttribute('x', $scale($c * $field['cell']))
                ->setAttribute('y', $scale($r * $field['cell']))->setAttribute('width', $scale($field['cell']))
                ->setAttribute('height', $scale($field['cell']))->setAttribute('fill-opacity', (string) round(0.08 + 0.5 * $v, 3)));
        }
        $svg->addItem($group);
    }
    $markers = array_column($selected['markers'], null, 'ap_uid');
    foreach ($selected['reuse'] as $pair) {
        $a = $markers[$pair['a']];
        $b = $markers[$pair['b']];
        $svg->addItem((new CTag('line', true, (new CTag('title', true, _s('Channel %1$s: %2$s', implode(', ', $pair['channels']),
                $pair['heard'] ? _('one AP hears the other (observed)') : _('channel reuse, no RF evidence'))))))
            ->addClass($pair['heard'] ? 'we-reuse-heard' : 'we-reuse')
            ->setAttribute('x1', $scale($a['x']))->setAttribute('y1', $scale($a['y']))
            ->setAttribute('x2', $scale($b['x']))->setAttribute('y2', $scale($b['y'])));
    }
    foreach ($selected['markers'] as $marker) {
        $label = $marker['name'] ?? _('Unnamed access point');
        switch ($selected['overlay']) {
            case 'band':
                $value = implode('/', array_unique(array_map(static fn($r) => $r['band'] ?? '?', $marker['radios']))) ?: '—';
                break;
            case 'channel':
                $value = implode(', ', array_map(static fn($r) => $r['channel'] ?? '—', $marker['radios'])) ?: '—';
                break;
            case 'utilisation':
                $value = $marker['utilisation'] !== null ? $marker['utilisation'].'%' : '?';
                break;
            case 'clients':
                $value = $marker['clients'] ?? '?';
                break;
            case 'neighbours':
                $value = $marker['neighbours'] === null ? '?' : $marker['neighbours']
                    .($marker['flagged'] ? ' ('.$marker['flagged'].' '._('flagged').')' : '');
                break;
            default:
                $value = '';
        }
        $state = $marker['status'].($marker['degraded'] ? '-degraded' : '');
        $group = (new CTag('a', true))->setAttribute('href', $link(['view'=>'floors', 'floor'=>$selected['floor_id'],
            'overlay'=>$selected['overlay'], 'band'=>$selected['band'], 'ap'=>$marker['ap_uid']]))
            ->addClass('we-marker')->addClass('we-marker-'.$state)->setAttribute('data-ap', $marker['ap_uid']);
        if ($marker['ap_uid'] === $data['selected_ap']) {
            $group->addClass('we-marker-selected');
        }
        $group->addItem(new CTag('title', true, $label.' · '.$marker['status'].($value !== '' ? ' · '.$value : '')));
        $group->addItem((new CTag('circle', true))->setAttribute('cx', $scale($marker['x']))->setAttribute('cy', $scale($marker['y']))
            ->setAttribute('r', '11'));
        $group->addItem((new CTag('text', true, $label))->addClass('we-marker-name')
            ->setAttribute('x', $scale($marker['x']))->setAttribute('y', (string) round($marker['y'] * 1000 - 16, 1)));
        if ($value !== '') {
            $group->addItem((new CTag('text', true, (string) $value))->addClass('we-marker-value')
                ->setAttribute('x', $scale($marker['x']))->setAttribute('y', (string) round($marker['y'] * 1000 + 28, 1)));
        }
        $svg->addItem($group);
    }
    $canvas = (new CDiv($svg))->addClass('we-floor-canvas');
    $root->addItem($canvas);

    // Placement: a Super admin picks an AP, then clicks its position on the plan. Positions are configuration.
    if ($data['can_configure'] ?? false) {
        $choices = (new CSelect('ap_uid'))->setId('we-place-ap')->addOption(new CSelectOption('', _('Select an AP')));
        $site = $selected['site'];
        foreach ($data['aps'] as $ap) {
            if ($ap['site'] === $site || $ap['site'] === '') {
                $choices->addOption(new CSelectOption($ap['ap_uid'], ($ap['name'] ?? $ap['ap_uid'])
                    .($ap['placement'] === null ? ' — '._('unplaced') : '')));
            }
        }
        if ($data['selected_ap'] !== '') {
            $choices->setValue($data['selected_ap']);
        }
        $root->addItem((new CDiv([new CLabel(_('Place AP'), 'we-place-ap-button'),
            $choices->setFocusableElementId('we-place-ap-button'),
            (new CSpan(_('then click its position on the plan.')))->addClass('we-hint'),
            (new CButton('we-place-remove', _('Remove placement')))->addClass(ZBX_STYLE_BTN_ALT)->setId('we-place-remove'),
            (new CSpan(''))->setId('we-place-status')->setAttribute('role', 'status')]))
            ->addClass('we-placement')
            ->setAttribute('data-action', 'wifiexplorer.placement.update')
            ->setAttribute('data-token', CCsrfTokenHelper::get('wifiexplorer.placement.update'))
            ->setAttribute('data-floor', $selected['floor_id']));
    }
}

// APs with no placement are listed, never dropped from the floor view.
$unplaced = (new CTableInfo())->setHeader([_('Access point'), _('Site'), _('Status'), _('Model')])
    ->setNoDataMessage(_('Every visible AP has a placement.'));
foreach ($floors['unplaced'] as $apUid) {
    $ap = $byUid[$apUid];
    $unplaced->addRow([new CLink($ap['name'] ?? _('Unnamed access point'), $link(['ap'=>$apUid, 'view'=>'floors',
        'floor'=>$selected['floor_id'] ?? ''])), $ap['site'] !== '' ? $ap['site'] : _('Unknown'),
        $status($ap['status'], $ap['status_reason']), $unknown($ap['model'])]);
}
$root->addItem([new CTag('h2', true, _s('Unplaced APs (%1$s)', count($floors['unplaced']))), $unplaced]);
