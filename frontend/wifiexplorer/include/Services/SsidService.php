<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * SSID inventory (requirements section 11): what each cluster reports, merged with declared intent.
 *
 * Observed: the cluster's SSID table (name, enabled, hidden, client count). Declared: the operator's SSID intent
 * (VLAN, where it is expected, which bands). The VLAN is never inferred: AI-AP-MIB on Instant does not expose it,
 * so an SSID without intent has an unknown VLAN and its service path cannot be checked.
 *
 * Whether an expected AP broadcasts an SSID is inferred, never observed: the SSID is enabled on the AP's cluster,
 * the AP is up, and a radio is up in an expected band. Instant zones can restrict an SSID to some APs and the MIB
 * does not report them, so the page says "inferred".
 */
final class SsidService {
    /**
     * @param array $owners   hostid => owner
     * @param array $datasets hostid => dataset => envelope
     * @param array $aps      ap_uid => AP (with site, status, radios, placement)
     * @param array $config   the viewer's part of the configuration (WifiConfig::visible)
     * @return array{ssids: array, by_ap: array, findings: array}
     */
    public function build(array $owners, array $datasets, array $aps, array $config): array {
        $clusters = [];
        $observed = [];
        foreach ($owners as $hostid => $owner) {
            $set = $datasets[$hostid]['ssid'] ?? null;
            if ($set === null) {
                continue;
            }
            $hostid = (string) $hostid;
            $current = ($set['freshness'] ?? 'unknown') === 'current';
            $clusters[$hostid] = ['hostid'=>$hostid, 'name'=>$owner['name'], 'site'=>$owner['site'],
                'current'=>$current, 'freshness'=>$set['freshness'] ?? 'unknown',
                'observed_at'=>$set['observed_at'] ?? null, 'rows'=>[]];
            foreach ($set['data'] as $row) {
                $clusters[$hostid]['rows'][$row['ssid_uid']] = $row;
                $observed[$row['ssid_uid']] = $row['name'];
            }
        }
        $intents = [];
        foreach ($config['ssids'] as $intent) {
            $intents[$intent['ssid_uid']][$intent['site']] = $intent;
            $observed[$intent['ssid_uid']] = $observed[$intent['ssid_uid']] ?? $intent['ssid'];
        }
        $sites = [];
        foreach ($aps as $ap) {
            $sites[$ap['site']] = true;
        }

        $ssids = [];
        $byAp = [];
        $findings = [];
        foreach ($observed as $uid => $name) {
            $observations = [];
            foreach ($clusters as $cluster) {
                $row = $cluster['rows'][$uid] ?? null;
                if ($row !== null) {
                    $observations[] = ['hostid'=>$cluster['hostid'], 'owner_name'=>$cluster['name'],
                        'site'=>$cluster['site'], 'enabled'=>$row['enabled'], 'hidden'=>$row['hidden'],
                        'client_count'=>$row['client_count'], 'freshness'=>$cluster['freshness'],
                        'observed_at'=>$cluster['observed_at']];
                }
            }
            // Intent per site: a site's own declaration, else one for every site ('').
            $applied = [];
            foreach (array_keys($sites + ($intents[$uid] ?? [])) as $site) {
                if ($site === '') {
                    continue;
                }
                $intent = $intents[$uid][$site] ?? $intents[$uid][''] ?? null;
                if ($intent !== null) {
                    $applied[$site] = $intent;
                }
            }
            $expected = [];
            foreach ($aps as $apUid => $ap) {
                $intent = $applied[$ap['site']] ?? null;
                if ($intent !== null ? !self::expects($intent, $ap)
                        : !self::enabledOn($clusters[$ap['owner_hostid']]['rows'][$uid] ?? null)) {
                    continue;
                }
                $state = self::broadcast($ap, $clusters[$ap['owner_hostid']] ?? null, $uid, $intent['bands'] ?? []);
                $expected[$apUid] = ['ap_uid'=>$apUid, 'site'=>$ap['site'], 'vlan'=>$intent['vlan'] ?? null,
                    'basis'=>$intent !== null ? 'declared' : 'observed_cluster'] + $state;
                $byAp[$apUid][$uid] = $expected[$apUid];
            }
            $counts = array_fill_keys(['broadcasting', 'not_broadcasting', 'unknown'], 0);
            foreach ($expected as $row) {
                ++$counts[$row['status']];
            }
            $current = array_filter($observations, static fn($o) => $o['freshness'] === 'current');
            $entry = ['ssid_uid'=>$uid, 'name'=>$name, 'observations'=>$observations,
                'enabled'=>$current ? (bool) array_filter($current, static fn($o) => $o['enabled']) : null,
                'hidden'=>(bool) array_filter($observations, static fn($o) => $o['hidden'] === true),
                'clients'=>$current ? array_sum(array_map(static fn($o) => (int) $o['client_count'], $current)) : null,
                'clients_reported'=>(bool) array_filter($current, static fn($o) => $o['client_count'] !== null),
                'intent'=>array_values($applied), 'declared'=>$applied !== [],
                'vlans'=>array_map(static fn($i) => $i['vlan'], $applied),
                'expected'=>array_values($expected), 'counts'=>$counts];
            $ssids[] = $entry;
            $findings = array_merge($findings, $this->findings($entry, $clusters, $applied, $aps));
        }
        usort($ssids, static fn($a, $b) => strnatcasecmp($a['name'], $b['name']) ?: strcmp($a['ssid_uid'], $b['ssid_uid']));
        return ['ssids'=>$ssids, 'by_ap'=>$byAp, 'findings'=>$findings];
    }

    private static function expects(array $intent, array $ap): bool {
        if ($intent['expect'] === 'floors') {
            return $ap['placement'] !== null && in_array($ap['placement']['floor_id'], $intent['floors'], true);
        }
        if ($intent['expect'] === 'aps') {
            return in_array($ap['ap_uid'], $intent['aps'], true);
        }
        return true;
    }

    private static function enabledOn(?array $row): bool {
        return $row !== null && $row['enabled'] === true;
    }

    /** @return array{status: string, reason: ?string, kind: string} */
    private static function broadcast(array $ap, ?array $cluster, string $uid, array $bands): array {
        $result = static fn(string $status, ?string $reason) => ['status'=>$status, 'reason'=>$reason, 'kind'=>'inferred'];
        if ($cluster === null || !$cluster['current']) {
            return $result('unknown', 'ssid_state_unknown');
        }
        $row = $cluster['rows'][$uid] ?? null;
        if ($row === null) {
            return $result('not_broadcasting', 'not_on_cluster');
        }
        if ($row['enabled'] !== true) {
            return $result('not_broadcasting', 'disabled');
        }
        if ($ap['status'] === 'down') {
            return $result('not_broadcasting', 'ap_down');
        }
        if ($ap['status'] !== 'up') {
            return $result('unknown', 'ap_state_unknown');
        }
        $unknown = false;
        foreach ($ap['radios'] as $radio) {
            $inBand = $bands === [] || in_array($radio['band'], $bands, true);
            if ($radio['status'] === 'up' && $inBand && ($bands === [] || $radio['band'] !== null)) {
                return $result('broadcasting', null);
            }
            if ($radio['status'] === 'unknown' || $radio['status'] === 'up' && $radio['band'] === null) {
                $unknown = true;
            }
        }
        return $unknown ? $result('unknown', 'radio_state_unknown') : $result('not_broadcasting', 'no_radio_in_band');
    }

    private function findings(array $entry, array $clusters, array $applied, array $aps): array {
        $findings = [];
        $name = $entry['name'];
        foreach ($applied as $site => $intent) {
            $site = (string) $site;     // PHP turns an all-digit site key into an int.
            $here = array_filter($clusters, static fn($c) => $c['site'] === $site && $c['current']);
            if (!$here) {
                continue;
            }
            $listed = array_filter($here, static fn($c) => isset($c['rows'][$entry['ssid_uid']]));
            $evidence = array_map(static fn($c) => ['dataset'=>'ssid', 'hostid'=>$c['hostid'],
                'observed_at'=>$c['observed_at'], 'fact'=>isset($c['rows'][$entry['ssid_uid']])
                    ? ($c['rows'][$entry['ssid_uid']]['enabled'] ? 'enabled' : 'disabled') : 'not listed'], array_values($here));
            $owner = (string) array_key_first($here);
            if (!$listed) {
                $findings[] = WifiFinding::create('wifi_ssid_missing', 'warning', $owner, 'ssid', $entry['ssid_uid'],
                    _s('%1$s is declared for %2$s but no cluster there has it', $name, $site),
                    _('The SSID intent expects this network, and the current SSID tables of the site\'s clusters do not list it.'),
                    $evidence, 'current', _('Create the SSID on the cluster, or remove the intent under Configure.'));
                continue;
            }
            if (!array_filter($listed, static fn($c) => $c['rows'][$entry['ssid_uid']]['enabled'] === true)) {
                $findings[] = WifiFinding::create('wifi_ssid_disabled', 'warning', $owner, 'ssid', $entry['ssid_uid'],
                    _s('%1$s is disabled at %2$s', $name, $site),
                    _('The SSID intent expects this network, and every cluster at the site that has it reports it disabled.'),
                    $evidence, 'current', _('Enable the SSID on the cluster if it should be on air.'));
                continue;
            }
            $gaps = array_filter($entry['expected'], static fn($e) => $e['site'] === $site
                && $e['status'] === 'not_broadcasting' && in_array($e['reason'], ['ap_down', 'no_radio_in_band'], true));
            if ($gaps) {
                $findings[] = WifiFinding::create('wifi_ssid_coverage_gap', 'warning', $owner, 'ssid', $entry['ssid_uid'],
                    _s('%1$s: %2$s of %3$s expected APs at %4$s cannot broadcast it', $name, count($gaps),
                        count(array_filter($entry['expected'], static fn($e) => $e['site'] === $site)), $site),
                    _('Inferred from cluster SSID state, AP state and radio bands: these APs are down or have no radio up in an expected band.'),
                    array_map(static fn($e) => ['dataset'=>$e['reason'] === 'ap_down' ? 'ap_state' : 'radio_state',
                        'hostid'=>$aps[$e['ap_uid']]['owner_hostid'], 'observed_at'=>$aps[$e['ap_uid']]['state_observed_at'],
                        'fact'=>($aps[$e['ap_uid']]['name'] ?? $e['ap_uid']).': '.str_replace('_', ' ', $e['reason'])],
                        array_slice(array_values($gaps), 0, 10)),
                    'current', _('Bring the APs back, or check the radio profile against the declared bands.'), 'inferred');
            }
        }
        foreach ($entry['observations'] as $observation) {
            if ($observation['enabled'] && $observation['freshness'] === 'current' && !isset($applied[$observation['site']])) {
                $findings[] = WifiFinding::create('wifi_ssid_vlan_undeclared', 'info', $observation['hostid'], 'ssid',
                    $entry['ssid_uid'],
                    _s('%1$s on %2$s has no declared VLAN', $name, $observation['owner_name']),
                    _('Aruba Instant does not expose an SSID\'s VLAN over SNMP, so its wired service path cannot be checked until the VLAN is declared.'),
                    [['dataset'=>'ssid', 'hostid'=>$observation['hostid'], 'observed_at'=>$observation['observed_at'],
                        'fact'=>'enabled, no intent']], 'current',
                    _('Declare the SSID and its VLAN under Configure.'), 'declared');
            }
        }
        return $findings;
    }
}
