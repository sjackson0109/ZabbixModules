<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\ApiGateway;
use Modules\NetworkExplorer\Services\DataGateway;
use Modules\NetworkExplorer\Services\Limits;
use Modules\NetworkExplorer\Services\Navigation;
use Modules\NetworkExplorer\Services\NetworkScope;

/**
 * The permission-aware Wi-Fi model: acquisition owners, their APs and radios, the site overview, findings and data
 * quality, all from the current user's readable hosts.
 *
 * An AP is visible because a readable owner's dataset lists it; it is never assumed to be a polled endpoint. Every
 * count is computed from that visible set only. A state that is not current is reported as unknown, never as the
 * last value seen, so a stale "up" is never shown as healthy.
 */
final class WifiService {
    /** Wi-Fi capabilities this release does not collect; the overview names them instead of showing zeros. */
    public const NOT_AVAILABLE = ['poe', 'auth_failures', 'retry_rates'];
    private const BANDS = ['2.4', '5', '6'];

    private DataGateway $gateway;
    private ?int $now;
    private array $config;
    private bool $configInvalid;

    /** @param array|null $config a normalised configuration document (WifiConfig::normalise), or none */
    public function __construct(DataGateway $gateway, ?int $now = null, ?array $config = null,
            bool $configInvalid = false) {
        $this->gateway = $gateway;
        $this->now = $now;
        $this->config = $config ?? WifiConfig::empty();
        $this->configInvalid = $configInvalid;
    }

    public static function create(): self {
        try {
            return new self(new ApiGateway(), null, (new WifiConfigStore())->load());
        }
        catch (\RuntimeException $error) {
            return new self(new ApiGateway(), null, null, true);
        }
    }

    public function build(WifiScope $scope): array {
        $now = $this->now ?? time();
        $hosts = $this->owners($scope->site);
        $read = (new WifiDatasetReader($this->gateway, $now))->read($hosts);
        $datasets = $read['datasets'];
        $quality = $read['quality'];

        $owners = [];
        foreach ($hosts as $hostid => $host) {
            $device = $datasets[$hostid]['device']['data'][0] ?? null;
            // A host with only the per-AP RF producer observes RF for one AP; it owns no cluster data.
            $role = $device['role'] ?? (isset($datasets[$hostid]['rf_neighbour']) ? 'rf_observer' : 'unknown');
            $owners[$hostid] = $host + ['role'=>$role, 'vendor'=>$device['vendor'] ?? null,
                'platform'=>$device['platform'] ?? null, 'firmware'=>$device['firmware'] ?? null,
                'device_freshness'=>$datasets[$hostid]['device']['freshness'] ?? 'unknown'];
        }

        [$aps, $findings] = $this->accessPoints($owners, $datasets);
        if (count($aps) > WifiLimits::DISPLAY_APS) {
            throw new \RuntimeException('ap_budget_exceeded');
        }
        $findings = array_merge($findings, $this->qualityFindings($owners, $quality));
        // A host that lists no APs itself (a per-AP host) observes the one AP it polls.
        foreach ($owners as $hostid => $owner) {
            [$owners[$hostid]['observes_ap'], $owners[$hostid]['observes_basis']] = $owner['role'] === 'virtual_controller'
                ? [null, null] : RfService::attribute($owner, $aps);
        }

        $sites = array_values(array_unique(array_filter(array_column($owners, 'site'))));
        $config = WifiConfig::visible($this->config, $sites, array_keys($aps));
        $clientCounts = $this->clientCounts($owners, $datasets, $aps);
        foreach ($clientCounts as $apUid => $count) {
            $aps[$apUid]['clients'] = $count;
        }
        foreach ($aps as $apUid => &$ap) {
            $ap['clients'] = $ap['clients'] ?? null;
            $ap['placement'] = $config['placements'][$apUid] ?? null;
        }
        unset($ap);
        $rf = (new RfService())->build($owners, $datasets, $aps, $config['known_bssids']);
        $findings = array_merge($findings, $rf['findings']);
        $ssids = (new SsidService())->build($owners, $datasets, $aps, $config);
        $findings = array_merge($findings, $ssids['findings']);
        $wired = ['available'=>false, 'reason'=>'not_requested', 'switches'=>0];
        $paths = [];
        if ($scope->needsWired()) {
            try {
                $uplinks = (new UplinkService($this->gateway, $now))->build($scope->site, $owners, $aps);
            }
            catch (\RuntimeException $error) {
                $uplinks = ['available'=>false, 'reason'=>preg_match('/^[a-z_]{1,64}$/D', $error->getMessage())
                    ? $error->getMessage() : 'wired_read_failed', 'network'=>null, 'uplinks'=>[],
                    'findings'=>[]];
            }
            $wired = ['available'=>$uplinks['available'], 'reason'=>$uplinks['reason'],
                'switches'=>$uplinks['network'] !== null ? count($uplinks['network']['hosts']) : 0];
            foreach ($uplinks['uplinks'] as $apUid => $uplink) {
                $aps[$apUid]['uplink'] = $uplink;
            }
            $findings = array_merge($findings, $uplinks['findings']);
            if ($uplinks['available']) {
                $pathModel = (new PathService($uplinks['network']))->build($aps, $ssids['ssids']);
                $paths = $pathModel['paths'];
                foreach ($pathModel['chains'] as $apUid => $chain) {
                    $aps[$apUid]['chain'] = $chain;
                }
                $findings = array_merge($findings, $pathModel['findings']);
            }
        }
        foreach ($aps as $apUid => &$ap) {
            $ap['uplink'] = $ap['uplink'] ?? null;
            $ap['chain'] = $ap['chain'] ?? null;
            $ap['ssids'] = $ssids['by_ap'][$apUid] ?? [];
        }
        unset($ap);
        $floors = (new FloorService())->build($config, $aps, $clientCounts, $rf, $scope->floor, $scope->overlay,
            $scope->band);
        usort($findings, static fn($a, $b) => [$a['severity'] === 'warning' ? 0 : 1, $a['rule'], $a['title'], $a['id']]
            <=> [$b['severity'] === 'warning' ? 0 : 1, $b['rule'], $b['title'], $b['id']]);

        $selected = $scope->ap !== '' && isset($aps[$scope->ap]) ? $scope->ap : '';
        usort($owners, static fn($a, $b) => strnatcasecmp($a['name'], $b['name']) ?: (int) $a['hostid'] <=> (int) $b['hostid']);
        $list = array_values($aps);
        usort($list, static fn($a, $b) => [$a['site'], strtolower($a['name'] ?? "\u{10FFFF}"), $a['ap_uid']]
            <=> [$b['site'], strtolower($b['name'] ?? "\u{10FFFF}"), $b['ap_uid']]);

        return ['schema_version'=>'wifi-1.0', 'generated_at'=>gmdate('c', $now),
            'scope'=>$scope->describe() + ['owners'=>count($owners)],
            'owners'=>array_values($owners), 'aps'=>$list, 'overview'=>$this->overview($list, $quality, $findings),
            'findings'=>$findings, 'quality'=>$quality,
            'selected_ap'=>$selected, 'selection_missing'=>$scope->ap !== '' && $selected === '',
            'floors'=>$floors, 'rf'=>$rf, 'ssids'=>$ssids['ssids'], 'wired'=>$wired, 'paths'=>$paths,
            'config_invalid'=>$this->configInvalid,
            'intent'=>['ssids'=>$config['ssids'], 'events'=>$config['events'],
                'known_bssids'=>count($config['known_bssids'])],
            'budgets'=>$read['budgets'] + ['owner_host_limit'=>WifiLimits::OWNER_HOSTS,
                'display_ap_limit'=>WifiLimits::DISPLAY_APS]];
    }

    /** Sites carried by the Wi-Fi owners the user may read, for the scope selector. */
    public function siteOptions(): array {
        $sites = [];
        foreach ($this->owners('') as $host) {
            if ($host['site'] !== '') {
                $sites[$host['site']] = true;
            }
        }
        $sites = array_keys($sites);
        usort($sites, 'strnatcasecmp');
        return $sites;
    }

    /** Permitted hosts carrying a Wi-Fi producer, narrowed by site. */
    private function owners(string $site): array {
        $candidates = $site !== ''
            ? $this->gateway->hostids([['tag'=>NetworkScope::SITE_TAG, 'value'=>$site]], Limits::SCOPE_HOSTS)
            : null;
        $ids = $this->gateway->networkHostids(WifiDatasetReader::MEMBERSHIP,
            (WifiLimits::OWNER_HOSTS + 1) * count(WifiDatasetReader::MEMBERSHIP), $candidates);
        if (count($ids) > WifiLimits::OWNER_HOSTS) {
            throw new \RuntimeException('owner_budget_exceeded');
        }
        $hosts = [];
        foreach ($ids ? $this->gateway->hosts($ids) : [] as $row) {
            $hostid = (string) $row['hostid'];
            $value = NetworkScope::tagValue($row['tags'] ?? [], NetworkScope::SITE_TAG);
            if ($site !== '' && $value !== $site) {
                continue;
            }
            $available = null;
            $addresses = [];
            foreach ($row['interfaces'] ?? [] as $interface) {
                if ((int) ($interface['type'] ?? 0) === INTERFACE_TYPE_SNMP) {
                    if ((int) ($interface['useip'] ?? 1) === INTERFACE_USE_IP && is_string($interface['ip'] ?? null)
                            && filter_var($interface['ip'], FILTER_VALIDATE_IP)) {
                        $addresses[] = $interface['ip'];
                    }
                    $state = (int) ($interface['available'] ?? 0);
                    $available = $state === INTERFACE_AVAILABLE_TRUE ? true
                        : ($state === INTERFACE_AVAILABLE_FALSE ? false : $available);
                }
            }
            $hosts[$hostid] = ['hostid'=>$hostid, 'name'=>(string) ($row['name'] ?? $row['host'] ?? $hostid),
                'site'=>$value, 'domain'=>NetworkScope::tagValue($row['tags'] ?? [], NetworkScope::DOMAIN_TAG),
                'snmp_available'=>$available, 'addresses'=>$addresses,
                'dashboard_url'=>Navigation::dashboard($hostid)];
        }
        return $hosts;
    }

    /**
     * APs and their radios. Each AP has exactly one owner: when several readable owners list the same AP, the one
     * with the newest inventory observation (then the lowest host ID) owns it, and a finding says so.
     */
    private function accessPoints(array $owners, array $datasets): array {
        $claims = [];
        $findings = [];
        foreach ($owners as $hostid => $owner) {
            $sets = $datasets[$hostid] ?? [];
            $inventory = self::byKey($sets['ap_inventory']['data'] ?? [], 'ap_uid');
            $state = self::byKey($sets['ap_state']['data'] ?? [], 'ap_uid');
            $radioInventory = self::byKey($sets['radio_inventory']['data'] ?? [], 'radio_uid');
            $radioState = self::byKey($sets['radio_state']['data'] ?? [], 'radio_uid');
            $radios = [];
            foreach (array_keys($radioInventory + $radioState) as $radioUid) {
                $apUid = ($radioInventory[$radioUid] ?? $radioState[$radioUid])['ap_uid'];
                $radios[$apUid][] = $this->radio($radioInventory[$radioUid] ?? null, $radioState[$radioUid] ?? null,
                    $sets['radio_state'] ?? null);
            }
            foreach (array_keys($inventory + $state + $radios) as $apUid) {
                $claims[$apUid][] = ['hostid'=>(string) $hostid, 'inventory'=>$inventory[$apUid] ?? null,
                    'state'=>$state[$apUid] ?? null, 'radios'=>$radios[$apUid] ?? [],
                    'observed'=>(string) ($sets['ap_inventory']['observed_at'] ?? ''),
                    'state_set'=>$sets['ap_state'] ?? null, 'inventory_set'=>$sets['ap_inventory'] ?? null];
            }
        }
        $aps = [];
        $unproven = [];
        foreach ($claims as $apUid => $list) {
            usort($list, static fn($a, $b) => strcmp($b['observed'], $a['observed']) ?: (int) $a['hostid'] <=> (int) $b['hostid']);
            $claim = $list[0];
            $owner = $owners[$claim['hostid']];
            $ap = $this->accessPoint((string) $apUid, $claim, $owner);
            $aps[$apUid] = $ap;
            if (count($list) > 1) {
                $findings[] = WifiFinding::create('wifi_ap_multiple_owners', 'info', $claim['hostid'], 'ap', (string) $apUid,
                    _s('%1$s is listed by %2$s data sources', self::label($ap), count($list)),
                    _s('Shown from %1$s, which has the newest inventory. Link the Wi-Fi template to one host per cluster.',
                        $owner['name']),
                    array_map(static fn($c) => ['dataset'=>'ap_inventory', 'hostid'=>$c['hostid'],
                        'observed_at'=>$c['observed'] ?: null, 'fact'=>'lists this AP'], $list),
                    $ap['inventory_freshness']);
            }
            foreach ($this->apFindings($ap, $owner) as $finding) {
                $findings[] = $finding;
            }
            foreach ($ap['radios'] as $radio) {
                if ($radio['band'] === null && $radio['channel'] !== null) {
                    $unproven[$claim['hostid']] = ($unproven[$claim['hostid']] ?? 0) + 1;
                }
            }
        }
        foreach ($unproven as $hostid => $count) {
            $findings[] = WifiFinding::create('wifi_radio_band_unknown', 'info', (string) $hostid, 'owner', null,
                _s('%1$s: %2$s radios have no proven band', $owners[$hostid]['name'], $count),
                _('Their channel numbers are valid in more than one band (6 GHz channel numbers overlap 2.4 and 5 GHz), and the source does not say which. They count as unknown in the band distribution.'),
                [['dataset'=>'radio_state', 'hostid'=>(string) $hostid, 'observed_at'=>null, 'fact'=>'radio_band_ambiguous']],
                'current', null, 'observed');
        }
        return [$aps, $findings];
    }

    private function accessPoint(string $apUid, array $claim, array $owner): array {
        $inventory = $claim['inventory'] ?? [];
        $state = $claim['state'];
        $stateSet = $claim['state_set'];
        $stateFreshness = $stateSet['freshness'] ?? 'unknown';
        [$status, $reason] = self::effective($state['status'] ?? null, $state !== null, $stateSet !== null, $stateFreshness);
        $radios = $claim['radios'];
        usort($radios, static fn($a, $b) => [$a['radio_index'] ?? 999, $a['radio_uid']] <=> [$b['radio_index'] ?? 999, $b['radio_uid']]);
        $radioDown = array_filter($radios, static fn($r) => $r['status'] === 'down');
        return ['ap_uid'=>$apUid, 'owner_hostid'=>$claim['hostid'], 'owner_name'=>$owner['name'],
            'owner_role'=>$owner['role'], 'site'=>$owner['site'],
            'name'=>$inventory['name'] ?? null, 'mac_address'=>$inventory['mac_address'] ?? null,
            'ip_address'=>$inventory['ip_address'] ?? null, 'serial'=>$inventory['serial'] ?? null,
            'model'=>$inventory['model'] ?? null,
            // The AP's own firmware when the source reports it, else the cluster firmware from the owner.
            'firmware'=>$inventory['firmware'] ?? null, 'cluster_firmware'=>$owner['firmware'],
            'in_inventory'=>$claim['inventory'] !== null,
            'inventory_observed_at'=>$claim['inventory_set']['observed_at'] ?? null,
            'inventory_freshness'=>$claim['inventory_set']['freshness'] ?? 'unknown',
            'status'=>$status, 'status_reason'=>$reason, 'reported_status'=>$state['status'] ?? null,
            'uptime_s'=>$state['uptime_s'] ?? null, 'cpu_percent'=>$state['cpu_percent'] ?? null,
            'memory_used_percent'=>$state['memory_used_percent'] ?? null,
            'state_observed_at'=>$stateSet['observed_at'] ?? null, 'state_freshness'=>$stateFreshness,
            'degraded'=>$status === 'up' && $radioDown !== [],
            'radios'=>$radios];
    }

    private function radio(?array $inventory, ?array $state, ?array $stateSet): array {
        $freshness = $stateSet['freshness'] ?? 'unknown';
        [$status, $reason] = self::effective($state['status'] ?? null, $state !== null, $stateSet !== null, $freshness);
        $row = $state ?? [];
        return ['radio_uid'=>($inventory ?? $state)['radio_uid'], 'ap_uid'=>($inventory ?? $state)['ap_uid'],
            'radio_index'=>$inventory['radio_index'] ?? null, 'bssid'=>$inventory['bssid'] ?? null,
            'status'=>$status, 'status_reason'=>$reason, 'reported_status'=>$row['status'] ?? null,
            'band'=>$row['band'] ?? null, 'channel'=>$row['channel'] ?? null,
            'channel_width'=>$row['channel_width'] ?? null, 'tx_power_dbm'=>$row['tx_power_dbm'] ?? null,
            'noise_floor_dbm'=>$row['noise_floor_dbm'] ?? null,
            'utilisation_percent'=>$row['utilisation_percent'] ?? null,
            'utilisation_window_s'=>$row['utilisation_window_s'] ?? null,
            'state_observed_at'=>$stateSet['observed_at'] ?? null, 'state_freshness'=>$freshness];
    }

    /**
     * The status to act on: the reported one only while its dataset is current.
     * @return array{0: string, 1: string|null} status and, when it is not the reported one, why
     */
    private static function effective(?string $reported, bool $present, bool $collected, string $freshness): array {
        if (!$collected) {
            return ['unknown', 'state_not_collected'];
        }
        if (!$present) {
            return ['unknown', 'absent_from_state'];
        }
        if ($freshness !== 'current') {
            return ['unknown', $freshness === 'stale' ? 'state_stale' : 'state_unknown'];
        }
        return [$reported ?? 'unknown', null];
    }

    private function apFindings(array $ap, array $owner): array {
        $findings = [];
        $label = self::label($ap);
        if ($ap['status'] === 'down') {
            $findings[] = WifiFinding::create('wifi_ap_down', 'warning', $ap['owner_hostid'], 'ap', $ap['ap_uid'],
                _s('%1$s is down', $label),
                _s('%1$s reports this AP down.', $owner['name']),
                [['dataset'=>'ap_state', 'hostid'=>$ap['owner_hostid'], 'observed_at'=>$ap['state_observed_at'],
                    'fact'=>'status down']], $ap['state_freshness'],
                _('Check the AP\'s power (PoE) and its switch port, then the controller\'s view of the AP.'));
        }
        if ($ap['status'] !== 'up') {
            return $findings;
        }
        foreach ($ap['radios'] as $radio) {
            $name = $label.' '._s('radio %1$s', $radio['radio_index'] ?? '?');
            $evidence = ['dataset'=>'radio_state', 'hostid'=>$ap['owner_hostid'],
                'observed_at'=>$radio['state_observed_at']];
            if ($radio['status'] === 'down') {
                $findings[] = WifiFinding::create('wifi_radio_down', 'warning', $ap['owner_hostid'], 'radio',
                    $radio['radio_uid'], _s('%1$s is down', $name),
                    _('The AP is up but reports this radio down.'),
                    [$evidence + ['fact'=>'status down']], $radio['state_freshness'],
                    _('Check whether the radio was disabled on purpose; if not, check the AP\'s radio profile.'));
            }
            if ($radio['status'] === 'up' && $radio['utilisation_percent'] !== null
                    && $radio['utilisation_percent'] >= WifiLimits::HIGH_UTILISATION) {
                $window = $radio['utilisation_window_s'] !== null ? _s('%1$s-second', $radio['utilisation_window_s']) : '';
                $findings[] = WifiFinding::create('wifi_radio_high_utilisation', 'warning', $ap['owner_hostid'],
                    'radio', $radio['radio_uid'],
                    _s('%1$s channel utilisation %2$s%%', $name, $radio['utilisation_percent']),
                    _s('Observed %1$s channel utilisation is at or above %2$s%%. One sample is not a trend; check its history before acting.',
                        $window, WifiLimits::HIGH_UTILISATION),
                    [$evidence + ['fact'=>'utilisation '.$radio['utilisation_percent'].'%']], $radio['state_freshness']);
            }
        }
        return $findings;
    }

    /** One finding per owner dataset that is not current, so a dead source is never mistaken for a quiet one. */
    private function qualityFindings(array $owners, array $quality): array {
        $findings = [];
        foreach ($quality as $row) {
            $owner = $owners[$row['hostid']] ?? null;
            if ($owner === null) {
                continue;
            }
            $evidence = [['dataset'=>$row['dataset'], 'hostid'=>$row['hostid'], 'observed_at'=>$row['observed_at'],
                'fact'=>$row['status'].($row['errors'] ? ' ('.implode(', ', $row['errors']).')' : '')]];
            if ($row['status'] === 'unsupported') {
                // A member AP: one finding for the host, not one per dataset.
                if ($row['dataset'] === 'ap_inventory') {
                    $member = in_array('not_virtual_controller', $row['errors'], true) || $owner['role'] === 'member';
                    $findings[] = WifiFinding::create($member ? 'wifi_owner_not_controller' : 'wifi_owner_unsupported',
                        'info', $row['hostid'], 'owner', null,
                        $member ? _s('%1$s is not the virtual controller', $owner['name'])
                            : _s('%1$s does not expose this Wi-Fi source', $owner['name']),
                        $member ? _('Only the elected virtual controller lists the cluster\'s APs and radios, so this host contributes none.')
                            : _('The device answered, but not with the data this Wi-Fi template reads.'),
                        $evidence, $row['freshness'],
                        $member ? _('Link the Wi-Fi Explorer template to one host per cluster, pointed at the cluster\'s floating virtual controller address.') : null);
                }
                continue;
            }
            if ($row['freshness'] === 'stale' || $row['status'] === 'failed') {
                $failed = $row['status'] === 'failed';
                $findings[] = WifiFinding::create($failed ? 'wifi_dataset_failed' : 'wifi_dataset_stale', 'warning',
                    $row['hostid'], 'owner', null,
                    $failed ? _s('%1$s: %2$s collection failed', $owner['name'], $row['dataset'])
                        : _s('%1$s: %2$s is stale', $owner['name'], $row['dataset']),
                    $row['retained']
                        ? _('The last complete observation is kept and shown, but anything derived from a stale dataset is reported as unknown.')
                        : _('No complete observation is available; objects from this dataset are reported as unknown.'),
                    $evidence, $row['freshness'],
                    _('Check the host\'s SNMP availability and the Wi-Fi Explorer collection items in Latest data.'));
            }
        }
        return $findings;
    }

    private function overview(array $aps, array $quality, array $findings): array {
        $count = static fn(array $rows, string $status) => count(array_filter($rows, static fn($r) => $r['status'] === $status));
        $radios = array_merge(...array_map(static fn($ap) => $ap['radios'], $aps ?: [['radios'=>[]]]));
        $bands = array_fill_keys(array_merge(self::BANDS, ['unknown']), 0);
        $utilisation = [];
        foreach ($radios as $radio) {
            $current = $radio['state_freshness'] === 'current';
            $band = $current && $radio['band'] !== null ? $radio['band'] : 'unknown';
            ++$bands[$band];
            if ($current && $radio['status'] === 'up' && $radio['utilisation_percent'] !== null) {
                $utilisation[$band][] = $radio['utilisation_percent'];
            }
        }
        $summary = [];
        foreach ($utilisation as $band => $values) {
            $summary[$band] = ['radios'=>count($values), 'average'=>(int) round(array_sum($values) / count($values)),
                'max'=>max($values)];
        }
        $high = count(array_filter($radios, static fn($r) => $r['state_freshness'] === 'current' && $r['status'] === 'up'
            && $r['utilisation_percent'] !== null && $r['utilisation_percent'] >= WifiLimits::HIGH_UTILISATION));
        $datasets = ['total'=>count($quality), 'current'=>0, 'stale'=>0, 'failed'=>0, 'unsupported'=>0, 'unknown'=>0];
        foreach ($quality as $row) {
            $state = $row['status'] === 'unsupported' ? 'unsupported' : ($row['status'] === 'failed' ? 'failed'
                : ($row['freshness'] === 'current' ? 'current' : ($row['freshness'] === 'stale' ? 'stale' : 'unknown')));
            ++$datasets[$state];
        }
        return ['aps'=>['total'=>count($aps), 'up'=>$count($aps, 'up'), 'down'=>$count($aps, 'down'),
                'unknown'=>$count($aps, 'unknown'), 'degraded'=>count(array_filter($aps, static fn($ap) => $ap['degraded']))],
            'radios'=>['total'=>count($radios), 'up'=>$count($radios, 'up'), 'down'=>$count($radios, 'down'),
                'unknown'=>$count($radios, 'unknown')],
            'bands'=>$bands, 'utilisation'=>$summary, 'high_utilisation_radios'=>$high,
            'high_utilisation_threshold'=>WifiLimits::HIGH_UTILISATION, 'datasets'=>$datasets,
            'findings'=>['warning'=>count(array_filter($findings, static fn($f) => $f['severity'] === 'warning')),
                'info'=>count(array_filter($findings, static fn($f) => $f['severity'] === 'info'))],
            'not_available'=>self::NOT_AVAILABLE];
    }

    /**
     * Current associated clients per AP from each AP's owner's client snapshot (observed). An AP whose owner's client
     * data is not current has no count rather than a stale one.
     */
    private function clientCounts(array $owners, array $datasets, array $aps): array {
        $counts = [];
        foreach ($aps as $apUid => $ap) {
            $set = $datasets[$ap['owner_hostid']]['client'] ?? null;
            if ($set !== null && ($set['freshness'] ?? '') === 'current') {
                $counts[$apUid] = 0;
            }
        }
        foreach ($owners as $hostid => $owner) {
            $set = $datasets[$hostid]['client'] ?? null;
            if ($set === null || ($set['freshness'] ?? '') !== 'current') {
                continue;
            }
            foreach ($set['data'] as $row) {
                $apUid = $row['ap_uid'] ?? null;
                if ($apUid !== null && isset($counts[$apUid]) && $aps[$apUid]['owner_hostid'] === (string) $hostid) {
                    ++$counts[$apUid];
                }
            }
        }
        return $counts;
    }

    private static function byKey(array $rows, string $key): array {
        $out = [];
        foreach ($rows as $row) {
            $out[$row[$key]] = $row;
        }
        return $out;
    }

    private static function label(array $ap): string {
        return $ap['name'] ?? _s('AP %1$s', substr($ap['ap_uid'], 3, 8));
    }
}
