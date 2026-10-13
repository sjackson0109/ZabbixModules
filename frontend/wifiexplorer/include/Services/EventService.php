<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Event readiness (requirements section 16): for each declared event, a checklist built only from Phases A-D and
 * the event's own declaration, and one status:
 *
 *   ready      every check passes;
 *   not_ready  at least one check fails;
 *   unknown    nothing fails, but at least one check cannot be shown from current observations.
 *
 * A warning (high channel utilisation now) is shown without changing the status. Credentials (PSK, RADIUS,
 * captive portal) are never read, so they are listed as not checked, never as passed.
 */
final class EventService {
    /**
     * @param array $events   visible declared events
     * @param array $ssids    SsidService rows
     * @param array $aps      ap_uid => AP (status, radios, placement, clients)
     * @param array $paths    ssid_uid => PathService path
     * @param array $wired    the wired model's availability
     */
    public function build(array $events, array $ssids, array $aps, array $paths, array $wired, int $now): array {
        $byName = [];
        foreach ($ssids as $ssid) {
            $byName[$ssid['name']] = $ssid;
        }
        $rows = [];
        $findings = [];
        foreach ($events as $event) {
            $row = $this->event($event, $byName[$event['ssid']] ?? null, $aps, $paths, $wired, $now);
            $rows[] = $row;
            if ($row['timing'] !== 'ended' && $row['status'] !== 'ready') {
                $failing = array_filter($row['checks'], static fn($c) => $c['status'] === ($row['status'] === 'not_ready' ? 'fail' : 'unknown'));
                $findings[] = WifiFinding::create($row['status'] === 'not_ready' ? 'wifi_event_not_ready' : 'wifi_event_unknown',
                    $row['status'] === 'not_ready' ? 'warning' : 'info', null, 'event', $event['event_id'],
                    $row['status'] === 'not_ready' ? _s('%1$s is not ready', $event['name'])
                        : _s('%1$s readiness cannot be shown', $event['name']),
                    implode(' ', array_map(static fn($c) => $c['detail'], $failing)),
                    [['dataset'=>'event', 'hostid'=>null, 'observed_at'=>null,
                        'fact'=>implode(', ', array_column($failing, 'check'))]],
                    $row['status'] === 'not_ready' ? 'current' : 'unknown',
                    _('Open the event in Wi-Fi Explorer for the checklist.'), 'inferred');
            }
        }
        usort($rows, static fn($a, $b) => strcmp($a['starts'], $b['starts']) ?: strcmp($a['event_id'], $b['event_id']));
        return ['events'=>$rows, 'findings'=>$findings];
    }

    private function event(array $event, ?array $ssid, array $aps, array $paths, array $wired, int $now): array {
        $starts = strtotime($event['starts']);
        $ends = strtotime($event['ends']);
        $timing = $now < $starts ? 'upcoming' : ($now <= $ends ? 'in_progress' : 'ended');
        $checks = [];
        $check = static function (string $name, string $status, string $detail, string $kind) use (&$checks): void {
            $checks[] = ['check'=>$name, 'status'=>$status, 'detail'=>$detail, 'kind'=>$kind];
        };

        // Which APs serve the event: the event's floors, else everywhere the SSID is expected at the event's site.
        $expected = [];
        foreach ($ssid['expected'] ?? [] as $row) {
            if ($row['site'] === $event['site']) {
                $expected[$row['ap_uid']] = $row;
            }
        }
        if ($event['floors'] !== []) {
            foreach ($aps as $apUid => $ap) {
                $onFloor = $ap['site'] === $event['site'] && $ap['placement'] !== null
                    && in_array($ap['placement']['floor_id'], $event['floors'], true);
                if (!$onFloor) {
                    unset($expected[$apUid]);
                }
                elseif (!isset($expected[$apUid])) {
                    $expected[$apUid] = ['ap_uid'=>$apUid, 'status'=>'not_broadcasting', 'reason'=>'not_expected_for_ssid',
                        'vlan'=>null];
                }
            }
        }
        $required = $event['min_aps'] ?? count($expected);

        // Only the clusters of the event's own site count: the SSID may be on elsewhere and off here.
        $local = array_filter($ssid['observations'] ?? [], static fn($o) => $o['site'] === $event['site']);
        $current = array_filter($local, static fn($o) => $o['freshness'] === 'current');
        $enabled = $current ? (bool) array_filter($current, static fn($o) => $o['enabled']) : null;
        if ($ssid === null || $local === []) {
            $check('ssid_enabled', $ssid !== null && $ssid['declared'] ? 'fail' : 'unknown',
                _s('No visible cluster at this site reports %1$s.', $event['ssid']), 'observed');
        }
        elseif ($enabled === null) {
            $check('ssid_enabled', 'unknown', _s('The SSID state of %1$s is not current.', $event['ssid']), 'observed');
        }
        else {
            $check('ssid_enabled', $enabled ? 'pass' : 'fail', $enabled
                ? _s('%1$s is enabled on the cluster.', $event['ssid']) : _s('%1$s is disabled on the cluster.', $event['ssid']),
                'observed');
        }

        if (!$expected) {
            $check('aps_expected', 'fail', _('No visible AP is expected to serve this event (check the floors and placements).'),
                'configured');
        }
        else {
            $up = count(array_filter($expected, static fn($e) => ($aps[$e['ap_uid']]['status'] ?? 'unknown') === 'up'));
            $unknown = count(array_filter($expected, static fn($e) => ($aps[$e['ap_uid']]['status'] ?? 'unknown') === 'unknown'));
            $check('aps_up', $up >= $required ? 'pass' : ($up + $unknown >= $required ? 'unknown' : 'fail'),
                _s('%1$s of %2$s APs up (%3$s needed, %4$s unknown).', $up, count($expected), $required, $unknown), 'observed');
            $on = count(array_filter($expected, static fn($e) => $e['status'] === 'broadcasting'));
            $maybe = count(array_filter($expected, static fn($e) => $e['status'] === 'unknown'));
            $check('broadcasting', $on >= $required ? 'pass' : ($on + $maybe >= $required ? 'unknown' : 'fail'),
                _s('%1$s of %2$s APs can broadcast %3$s in its bands (%4$s needed).', $on, count($expected), $event['ssid'],
                    $required), 'inferred');

            // An AP serves the event when it can broadcast the SSID and its VLAN path has not failed.
            $serving = array_filter($expected, static fn($e) => $e['status'] === 'broadcasting');
            // APs whose broadcasting is unknown may still serve: they make capacity unknown, never failed.
            $possible = array_filter($expected, static fn($e) => in_array($e['status'], ['broadcasting', 'unknown'], true));
            if (!$wired['available']) {
                $check('vlan_paths', 'unknown', WifiErrors::wired($wired['reason']), 'inferred');
            }
            else {
                $results = $paths[$ssid['ssid_uid'] ?? '']['results'] ?? [];
                $state = static fn($e) => $results[$e['ap_uid']]['status'] ?? 'unknown';
                $complete = count(array_filter($serving, static fn($e) => $state($e) === 'complete'));
                $failed = array_filter($serving, static fn($e) => $state($e) === 'failed');
                $serving = array_filter($serving, static fn($e) => $state($e) !== 'failed');
                $possible = array_filter($possible, static fn($e) => $state($e) !== 'failed');
                $check('vlan_paths', $complete >= $required ? 'pass' : (count($serving) >= $required ? 'unknown' : 'fail'),
                    _s('VLAN path complete for %1$s of %2$s broadcasting APs (%3$s needed).', $complete,
                        $on, $required).($failed ? ' '._s('Failed for %1$s.', implode(', ', array_map(
                        static fn($e) => $aps[$e['ap_uid']]['name'] ?? $e['ap_uid'], $failed))) : ''),
                    'observed');
            }

            if ($event['expected_clients'] !== null) {
                $capacity = count($serving) * $event['clients_per_ap'];
                $check('capacity', $capacity >= $event['expected_clients'] ? 'pass'
                    : (count($possible) * $event['clients_per_ap'] >= $event['expected_clients'] ? 'unknown' : 'fail'),
                    _s('%1$s serving APs × %2$s clients each = %3$s for %4$s expected clients.', count($serving),
                        $event['clients_per_ap'], $capacity, $event['expected_clients'])
                    .(count($possible) > count($serving)
                        ? ' '._s('%1$s more may serve; their state is unknown.', count($possible) - count($serving)) : ''),
                    'declared');
            }

            $busy = [];
            $measured = 0;
            foreach ($expected as $row) {
                foreach ($aps[$row['ap_uid']]['radios'] ?? [] as $radio) {
                    if ($radio['status'] !== 'up' || $radio['utilisation_percent'] === null) {
                        continue;
                    }
                    ++$measured;
                    if ($radio['utilisation_percent'] >= WifiLimits::HIGH_UTILISATION) {
                        $busy[] = $aps[$row['ap_uid']]['name'] ?? $row['ap_uid'];
                    }
                }
            }
            // Advisory only: with nothing measured it is not checked, never passed.
            if ($measured === 0) {
                $check('utilisation', 'not_checked', _('No expected AP reports channel utilisation, so it is not checked.'),
                    'not_collected');
            }
            else {
                $check('utilisation', $busy ? 'warn' : 'pass', $busy
                    ? _s('High channel utilisation now on %1$s (one sample, not a forecast).', implode(', ', array_unique($busy)))
                    : _s('No expected AP has high channel utilisation now (%1$s radios measured).', $measured), 'observed');
            }
        }
        $check('credentials', 'not_checked', _('Pre-shared keys, RADIUS and captive portals are not read by Wi-Fi Explorer, so they are not validated.'),
            'not_collected');

        $statuses = array_column($checks, 'status');
        $status = in_array('fail', $statuses, true) ? 'not_ready' : (in_array('unknown', $statuses, true) ? 'unknown' : 'ready');
        return ['event_id'=>$event['event_id'], 'name'=>$event['name'], 'site'=>$event['site'], 'ssid'=>$event['ssid'],
            'ssid_uid'=>$ssid['ssid_uid'] ?? null, 'starts'=>$event['starts'], 'ends'=>$event['ends'], 'timing'=>$timing,
            'floors'=>$event['floors'], 'min_aps'=>$event['min_aps'], 'expected_clients'=>$event['expected_clients'],
            'clients_per_ap'=>$event['clients_per_ap'], 'aps'=>array_keys($expected), 'status'=>$status, 'checks'=>$checks];
    }
}
