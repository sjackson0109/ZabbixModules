<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * Shared, permission-aware application layer for every widget, page and export.
 *
 * build() runs fixed stages: validate the scope, read the permitted hosts and their datasets, describe hosts and
 * interfaces, mask hidden bridges, build the topology, share aggregator state with LAG members, link the VLAN and
 * STP overlays, attach peers, add host findings, and finally narrow a seeded request to its one-hop neighbourhood.
 */
final class NetworkService {
    private const MAX_CIDRS = 32;
    private const MAX_CIDR_TEXT = 2048;
    private const MAX_STACK_MEMBERS = 16;
    private const INTERFACE_FIELDS = ['uid', 'if_index', 'name', 'description', 'alias', 'type', 'physical',
        'admin_status', 'oper_status', 'speed_bps', 'duplex', 'mtu', 'mac_address', 'expected_speed_bps', 'member',
        'slot', 'port'];
    private const CAPABILITY_FIELDS = ['autoneg_enabled', 'oper_speed_bps', 'oper_duplex', 'supported_speeds_bps',
        'advertised_speeds_bps', 'partner_advertised_speeds_bps'];

    private DataGateway $gateway;
    private ?int $now;
    /** Per-port expected speed overrides by hostid, from host macros. */
    private array $overrides = [];

    public function __construct(DataGateway $gateway, ?int $now = null) {
        $this->gateway = $gateway;
        $this->now = $now;
    }

    public static function create(): self {
        return new self(new ApiGateway());
    }

    public function build(array $hostids = [], string $managementCidr = ''): array {
        [$hostids, $cidrs] = $this->validateScope($hostids, $managementCidr);
        [$seeds, $hosts, $truncated] = $this->scopeHosts($hostids);
        $read = (new DatasetReader($this->gateway, $this->now))->read($hosts);
        // Hosts without any Network Explorer item (servers, other devices) are not part of the network view,
        // unless explicitly selected.
        $seedIds = array_fill_keys(array_map('strval', array_column($seeds, 'hostid')), true);
        $hosts = array_filter($hosts, static fn($host) => isset($read['collected'][$host['hostid']])
            || isset($seedIds[$host['hostid']]));
        $read['quality'] = array_values(array_filter($read['quality'],
            static fn($row) => isset($hosts[$row['hostid']])));
        $datasets = $read['datasets'];

        $layers = $this->indexLayers($hosts, $datasets);
        $findings = $this->describeHosts($hosts, $datasets, $layers, $cidrs);
        [$interfaces, $interfaceFindings] = $this->interfaces($hosts, $datasets, $layers, $read);
        $findings = array_merge($findings, $interfaceFindings);
        $this->maskHiddenBridges($layers);
        foreach ($layers['stp_bridges'] as $hostid => $rows) {
            $hosts[$hostid]['stp'] = $rows;
        }
        foreach ($interfaces as &$interface) {
            $interface['stp'] = $layers['stp_ports'][$interface['hostid']][$interface['uid']] ?? [];
        }
        unset($interface);

        $graph = (new TopologyService())->build($hosts, $datasets);
        $this->addEdgeLinks($graph['edges'], $hosts);
        $this->shareAggregatorState($graph['lags'], $layers, $interfaces);
        $labels = [];
        foreach ($interfaces as $interface) {
            $labels[$interface['hostid']][$interface['uid']] = $hosts[$interface['hostid']]['name'].' '
                .($interface['name'] ?? $interface['uid']);
        }
        $findings = array_merge($findings,
            VlanService::link($graph['edges'], $layers['vlan_ports'], array_map('array_filter', $layers['lldp']),
                $labels),
            StpService::link($graph['edges'], $layers['stp_bridges'], $layers['stp_ports'],
                array_column($hosts, 'domain', 'hostid')));
        $this->attachPeers($interfaces, $graph['edges'], $hosts);
        $findings = array_merge($findings, $this->healthFindings($hosts, $read['quality'], $truncated),
            $graph['findings']);

        $network = ['hosts'=>$hosts, 'interfaces'=>$interfaces, 'edges'=>$graph['edges'], 'lags'=>$graph['lags'],
            'quality'=>$read['quality'], 'findings'=>$findings];
        if ($hostids) {
            $network = $this->neighbourhood($network, $hostids, $seeds);
        }
        return ['schema_version'=>'1.1', 'generated_at'=>gmdate('c', $this->now ?? time()),
            'scope'=>['seed_hostids'=>$hostids, 'management_cidrs'=>$cidrs, 'truncated'=>$truncated,
                'neighbour_hops'=>$hostids ? 1 : 0],
            'hosts'=>array_values($network['hosts']), 'interfaces'=>$network['interfaces'],
            'edges'=>$network['edges'], 'lags'=>$network['lags'], 'quality'=>$network['quality'],
            'findings'=>$network['findings'],
            'budgets'=>$read['budgets']];
    }

    /** @return array{0: string[], 1: string[]} seed host IDs and management CIDRs */
    private function validateScope(array $hostids, string $managementCidr): array {
        $hostids = array_values(array_unique(array_map('strval', $hostids)));
        foreach ($hostids as $id) {
            if (!preg_match('/^[1-9][0-9]*$/D', $id)) {
                throw new \InvalidArgumentException('invalid_hostid');
            }
        }
        if (count($hostids) > Limits::HOSTS) {
            throw new \InvalidArgumentException('host_budget_exceeded');
        }
        if (strlen($managementCidr) > self::MAX_CIDR_TEXT) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $cidrs = trim($managementCidr) === '' ? [] : preg_split('/[\s,]+/', trim($managementCidr));
        if (count($cidrs) > self::MAX_CIDRS) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $subnet = new SubnetService();
        foreach ($cidrs as $cidr) {
            if (!$subnet->validate($cidr)) {
                throw new \InvalidArgumentException('invalid_management_cidr');
            }
        }
        return [$hostids, $cidrs];
    }

    /**
     * Seeds plus every permitted host in a seed's matching domain, or every permitted host when unseeded.
     * @return array{0: array, 1: array, 2: bool} seed rows, hosts by hostid, and whether the scope was capped
     */
    private function scopeHosts(array $hostids): array {
        $seeds = $hostids ? $this->gateway->hosts($hostids) : [];
        $rows = $this->gateway->hosts();
        $truncated = count($rows) > Limits::HOSTS;
        $hosts = [];
        $seedDomains = [];
        foreach ($seeds as $row) {
            $host = $this->host($row);
            $hosts[$host['hostid']] = $host;
            if ($host['domain'] !== '') {
                $seedDomains[$host['domain']] = true;
            }
        }
        foreach ($rows as $row) {
            $host = $this->host($row);
            if ($hostids && !isset($hosts[$host['hostid']])
                    && ($host['domain'] === '' || !isset($seedDomains[$host['domain']]))) {
                continue;
            }
            if (count($hosts) >= Limits::HOSTS && !isset($hosts[$host['hostid']])) {
                $truncated = true;
                continue;
            }
            $hosts[$host['hostid']] = $host;
        }
        // An inaccessible seed never turns into an all-host request.
        if ($hostids && !$seeds) {
            $hosts = [];
        }
        return [$seeds, $hosts, $truncated];
    }

    /**
     * Per-host lookups the later stages share: LLDP rows, VLAN port and STP rows by interface UID.
     * `vlans` and `stp_bridges` hold a host only when it reported that dataset.
     */
    private function indexLayers(array $hosts, array $datasets): array {
        $layers = ['lldp'=>[], 'vlans'=>[], 'vlan_ports'=>[], 'stp_bridges'=>[], 'stp_ports'=>[]];
        foreach (array_keys($hosts) as $hostid) {
            foreach (($datasets[$hostid]['lldp']['data'] ?? []) as $row) {
                // One neighbour per port is the normal case; several make the peer's capability ambiguous.
                $uid = $row['local_interface_uid'] ?? null;
                if (is_string($uid)) {
                    $layers['lldp'][$hostid][$uid] = isset($layers['lldp'][$hostid][$uid]) ? [] : $row;
                }
            }
            if (isset($datasets[$hostid]['vlan'])) {
                $layers['vlans'][$hostid] = [];
                foreach ($datasets[$hostid]['vlan']['data'] as $row) {
                    if ($row['kind'] === 'vlan') {
                        $layers['vlans'][$hostid][] = ['vlan_id'=>$row['vlan_id'], 'name'=>$row['name'] ?? null];
                    }
                    elseif (is_string($row['interface_uid'] ?? null)) {
                        $layers['vlan_ports'][$hostid][$row['interface_uid']] = VlanService::port($row);
                    }
                }
            }
            if (isset($datasets[$hostid]['stp'])) {
                [$layers['stp_bridges'][$hostid], $layers['stp_ports'][$hostid]] =
                    StpService::split($datasets[$hostid]['stp']['data']);
            }
        }
        return $layers;
    }

    /** Adds device, VLAN, STP and addressing details to each host. @return array findings */
    private function describeHosts(array &$hosts, array $datasets, array $layers, array $cidrs): array {
        $subnet = new SubnetService();
        $findings = [];
        foreach ($hosts as $hostid => &$host) {
            $host['vlans'] = $layers['vlans'][$hostid] ?? null;
            $host['stp'] = $layers['stp_bridges'][$hostid] ?? null;
            $device = $datasets[$hostid]['device']['data'][0] ?? [];
            foreach (['vendor', 'model', 'firmware', 'hostname'] as $field) {
                $host[$field] = is_string($device[$field] ?? null) ? $device[$field] : null;
            }
            $host['stack_members'] = [];
            $members = is_array($device['stack_members'] ?? null)
                ? array_slice($device['stack_members'], 0, self::MAX_STACK_MEMBERS) : [];
            foreach ($members as $member) {
                $host['stack_members'][] = array_map(static fn($v) => is_string($v) || is_int($v) ? $v : null,
                    array_intersect_key((array) $member + ['member'=>null, 'model'=>null, 'firmware'=>null],
                        array_flip(['member', 'model', 'firmware'])));
            }
            $host['management_addresses'] = $this->addresses(array_merge($host['management_addresses'],
                $device['management_addresses'] ?? []));
            $host['addressing'] = $subnet->annotate($host['management_addresses'], $cidrs);
            $host['out_of_subnet'] = in_array($host['addressing']['status'], ['outside', 'mixed'], true);
            if ($host['domain'] === '') {
                $findings[] = Finding::create('domain_unknown', 'info', (string) $hostid, 'Matching domain is unknown.',
                    'Assign a provisioner-controlled ne.domain host tag before peer matching.');
            }
        }
        unset($host);
        return $findings;
    }

    /**
     * One output row per reported interface, with derived speed intent, policy state and links.
     * @return array{0: array, 1: array} interfaces and their findings
     */
    private function interfaces(array $hosts, array $datasets, array $layers, array $read): array {
        $qualityIndex = [];
        foreach ($read['quality'] as $quality) {
            $qualityIndex[$quality['hostid']][$quality['dataset']] = $quality;
        }
        $policy = new PortPolicy();
        $interfaces = [];
        $findings = [];
        foreach (array_keys($hosts) as $hostid) {
            $hostid = (string) $hostid;
            $capabilities = array_column($datasets[$hostid]['port_capability']['data'] ?? [], null, 'uid');
            foreach (($datasets[$hostid]['interfaces']['data'] ?? []) as $row) {
                $output = array_intersect_key($row, array_flip(self::INTERFACE_FIELDS));
                $output['hostid'] = $hostid;
                $lldp = $layers['lldp'][$hostid][$row['uid']] ?? null;
                $capability = $capabilities[$row['uid']] ?? null;
                [$row['expected_speed_bps'], $row['expected_speed_source'], $basis] = SpeedIntent::derive($row,
                    $capability, $lldp ?: null, $this->overrides[$hostid] ?? []);
                $row['peer_duplex'] = $lldp['remote_duplex'] ?? null;
                $output['expected_speed_basis'] = $basis;
                $output['capability'] = $capability === null
                    ? null : array_intersect_key($capability, array_flip(self::CAPABILITY_FIELDS));
                $output['media'] = $capability['media'] ?? null;
                $output['vlan'] = $layers['vlan_ports'][$hostid][$row['uid']] ?? null;
                $output['itemid'] = $read['itemids'][$hostid][$row['uid']] ?? null;
                $quality = $qualityIndex[$hostid]['interfaces'];
                if (!($row['_state_present'] ?? false)) {
                    $quality['freshness'] = 'unknown';
                    $quality['errors'][] = 'interface_state_absent';
                }
                $output['quality'] = $quality;
                $evaluation = $policy->evaluate($row, $quality['freshness']);
                $output = array_replace($output, $evaluation);
                $output['observed_at'] = $quality['observed_at'];
                $output['dashboard_url'] = Navigation::dashboard($hostid, $row['uid']);
                $output['explorer_url'] = Navigation::explorer($hostid, $row['uid']);
                $output['peers'] = [];
                if ($evaluation['speed_degraded']) {
                    $findings[] = Finding::create('speed_below_intent',
                        $evaluation['speed_warning_confirmed'] ? 'warning' : 'info', $hostid,
                        'Speed below intended value.', $evaluation['reason'], $row['uid']);
                }
                if ($evaluation['duplex_mismatch']) {
                    $findings[] = Finding::create('duplex_mismatch', 'warning', $hostid, 'Duplex mismatch.',
                        'Half duplex against a full-duplex peer (from LLDP).', $row['uid']);
                }
                $interfaces[] = $output;
                if (count($interfaces) > Limits::INTERFACES) {
                    throw new \RuntimeException('interface_budget_exceeded');
                }
            }
        }
        return [$interfaces, $findings];
    }

    /**
     * A bridge ID embeds the bridge's MAC address, so one belonging to no permitted host is replaced by an opaque
     * token: equal IDs stay equal within this response, and nothing identifies the hidden bridge.
     */
    private function maskHiddenBridges(array &$layers): void {
        $visible = [];
        foreach ($layers['stp_bridges'] as $rows) {
            foreach ($rows as $row) {
                $visible[substr((string) ($row['bridge_id'] ?? ''), 4)] = true;
            }
        }
        $salt = random_bytes(16);
        $mask = static fn($id) => !is_string($id) || isset($visible[substr($id, 4)]) ? $id
            : 'undisclosed-'.substr(hash_hmac('sha256', $id, $salt), 0, 8);
        foreach ($layers['stp_bridges'] as &$rows) {
            foreach ($rows as &$row) {
                $row['root_bridge_id'] = $mask($row['root_bridge_id'] ?? null);
            }
            unset($row);
        }
        unset($rows);
        foreach ($layers['stp_ports'] as &$byUid) {
            foreach ($byUid as &$rows) {
                foreach ($rows as &$row) {
                    $row['designated_bridge'] = $mask($row['designated_bridge'] ?? null);
                }
                unset($row);
            }
            unset($rows);
        }
        unset($byUid);
    }

    private function addEdgeLinks(array &$edges, array $hosts): void {
        foreach ($edges as &$edge) {
            foreach (['source', 'target'] as $side) {
                $id = $edge[$side] ?? null;
                $uid = $edge[$side.'_uid'] ?? null;
                if ($id !== null && isset($hosts[(string) $id])) {
                    $edge[$side.'_dashboard_url'] = Navigation::dashboard((string) $id,
                        EnvelopeValidator::validUid($uid) ? $uid : null);
                }
            }
        }
        unset($edge);
    }

    /** VLAN and STP state belongs to the aggregator's bridge port; LAG members carry what their aggregator carries. */
    private function shareAggregatorState(array $lags, array &$layers, array &$interfaces): void {
        $viaLag = [];
        foreach ($lags as $lag) {
            $hostid = (string) $lag['hostid'];
            $aggregator = $lag['interface_uid'] ?? null;
            $via = ['via_lag'=>$lag['name'] ?? $aggregator];
            foreach ($lag['members'] as $member) {
                $uid = $member['interface_uid'] ?? null;
                if ($aggregator === null || $uid === null) {
                    continue;
                }
                if (!isset($layers['vlan_ports'][$hostid][$uid]) && isset($layers['vlan_ports'][$hostid][$aggregator])) {
                    $layers['vlan_ports'][$hostid][$uid] = $layers['vlan_ports'][$hostid][$aggregator] + $via;
                    $viaLag[$hostid][$uid] = true;
                }
                if (!isset($layers['stp_ports'][$hostid][$uid]) && isset($layers['stp_ports'][$hostid][$aggregator])) {
                    $layers['stp_ports'][$hostid][$uid] = array_map(static fn($row) => $row + $via,
                        $layers['stp_ports'][$hostid][$aggregator]);
                    $viaLag[$hostid][$uid] = true;
                }
            }
        }
        foreach ($interfaces as &$interface) {
            if (isset($viaLag[$interface['hostid']][$interface['uid']])) {
                $interface['vlan'] = $layers['vlan_ports'][$interface['hostid']][$interface['uid']] ?? null;
                $interface['stp'] = $layers['stp_ports'][$interface['hostid']][$interface['uid']] ?? [];
            }
        }
        unset($interface);
    }

    private function attachPeers(array &$interfaces, array $edges, array $hosts): void {
        $adjacency = [];
        foreach ($edges as $edge) {
            foreach (['source'=>'target', 'target'=>'source'] as $localSide => $side) {
                $localHost = $edge[$localSide] ?? null;
                $localUid = $edge[$localSide.'_uid'] ?? null;
                if ($localHost === null || $localUid === null) {
                    continue;
                }
                $peerId = $edge[$side] ?? null;
                $adjacency[$localHost][$localUid][] = ['hostid'=>$peerId, 'interface_uid'=>$edge[$side.'_uid'] ?? null,
                    'name'=>$peerId !== null ? ($hosts[$peerId]['name'] ?? 'Unresolved peer') : 'Unresolved peer',
                    'status'=>$edge['status'] ?? 'unknown',
                    'dashboard_url'=>$edge[$side.'_dashboard_url'] ?? null];
            }
        }
        foreach ($interfaces as &$interface) {
            $interface['peers'] = $adjacency[$interface['hostid']][$interface['uid']] ?? [];
        }
        unset($interface);
    }

    /** SNMP reachability, collection quality and scope findings. */
    private function healthFindings(array $hosts, array $quality, bool $truncated): array {
        $findings = [];
        foreach ($hosts as $hostid => $host) {
            if ($host['snmp_available'] === false) {
                $findings[] = Finding::create('snmp_unreachable', 'warning', (string) $hostid,
                    'SNMP agent is unreachable.', 'Zabbix marks the SNMP interface unavailable. Collection has stopped; '
                    .'the last successful observations are shown.');
            }
        }
        foreach ($quality as $row) {
            // One unreachable finding per host replaces a collection finding per dataset.
            if ($row['errors'] === ['agent_unreachable']) {
                continue;
            }
            if ($row['warnings'] ?? []) {
                $findings[] = Finding::create('collection_rows_skipped_'.$row['dataset'], 'info', $row['hostid'],
                    ucfirst($row['dataset']).' collection skipped some rows.',
                    'The rest of the dataset is current. Diagnostics: '.implode(', ', $row['warnings']).'.');
            }
            if ($row['status'] !== 'ok' || $row['freshness'] !== 'current') {
                $findings[] = Finding::create('collection_'.$row['dataset'],
                    $row['status'] === 'failed' ? 'warning' : 'info', $row['hostid'],
                    ucfirst($row['dataset']).' collection requires attention.',
                    'Outcome: '.$row['status'].'; observation: '.$row['freshness'].'.');
            }
        }
        if ($truncated) {
            $findings[] = Finding::create('scope_truncated', 'info', null, 'Host scope is bounded.',
                'Only the first '.Limits::HOSTS.' permitted hosts were read. Select a narrower host/domain scope.');
        }
        return $findings;
    }

    /**
     * Keeps the seeds and the hosts one hop from them. Peers are resolved against every permitted same-domain
     * candidate first; a neighbour's own peers are not added.
     */
    private function neighbourhood(array $network, array $hostids, array $seeds): array {
        $display = [];
        foreach ($seeds as $seed) {
            $display[(string) $seed['hostid']] = true;
        }
        foreach ($network['edges'] as $edge) {
            if (isset($display[$edge['source'] ?? '']) && in_array((string) ($edge['source'] ?? ''), $hostids, true)
                    && $edge['target'] !== null) {
                $display[(string) $edge['target']] = true;
            }
            if (isset($display[$edge['target'] ?? '']) && in_array((string) ($edge['target'] ?? ''), $hostids, true)
                    && $edge['source'] !== null) {
                $display[(string) $edge['source']] = true;
            }
        }
        $shown = static fn($hostid) => $hostid === null || isset($display[$hostid]);
        $network['hosts'] = array_intersect_key($network['hosts'], $display);
        $network['interfaces'] = array_values(array_filter($network['interfaces'],
            static fn($row) => isset($display[$row['hostid']])));
        $network['edges'] = array_values(array_filter($network['edges'],
            static fn($edge) => $shown($edge['source']) && $shown($edge['target'])));
        $edgeIds = array_fill_keys(array_column($network['edges'], 'id'), true);
        $keepEdges = static fn(array $ids) => array_values(array_filter($ids, static fn($id) => isset($edgeIds[$id])));
        $network['lags'] = array_values(array_filter($network['lags'], static fn($row) => isset($display[$row['hostid']])));
        foreach ($network['lags'] as &$lag) {
            $lag['edge_ids'] = $keepEdges($lag['edge_ids']);
            $lag['peer_hostids'] = array_values(array_filter($lag['peer_hostids'], static fn($id) => isset($display[$id])));
            foreach ($lag['members'] as &$member) {
                $member['edge_ids'] = $keepEdges($member['edge_ids']);
            }
            unset($member);
        }
        unset($lag);
        foreach ($network['interfaces'] as &$interface) {
            $interface['peers'] = array_values(array_filter($interface['peers'],
                static fn($peer) => $shown($peer['hostid'])));
        }
        unset($interface);
        $network['quality'] = array_values(array_filter($network['quality'],
            static fn($row) => isset($display[$row['hostid']])));
        $network['findings'] = array_values(array_filter($network['findings'], static fn($row) =>
            $shown($row['hostid']) && (!isset($row['edge_id']) || isset($edgeIds[$row['edge_id']]))));
        return $network;
    }

    private function host(array $row): array {
        $domains = [];
        foreach ($row['tags'] ?? [] as $tag) {
            if (($tag['tag'] ?? null) === 'ne.domain' && is_string($tag['value'] ?? null)
                    && $tag['value'] !== '' && strlen($tag['value']) <= 128) {
                $domains[$tag['value']] = true;
            }
        }
        $addresses = [];
        foreach ($row['interfaces'] ?? [] as $interface) {
            if ((int) ($interface['type'] ?? 0) === INTERFACE_TYPE_SNMP && (int) ($interface['useip'] ?? 0) === INTERFACE_USE_IP) {
                $addresses[] = $interface['ip'];
            }
        }
        // Zabbix marks an SNMP interface unavailable after timeouts; it records no failed value then.
        $available = null;
        foreach ($row['interfaces'] ?? [] as $interface) {
            if ((int) ($interface['type'] ?? 0) === INTERFACE_TYPE_SNMP && isset($interface['available'])) {
                $state = (int) $interface['available'];
                $available = $state === INTERFACE_AVAILABLE_FALSE
                    ? false
                    : ($state === INTERFACE_AVAILABLE_TRUE && $available !== false ? true : $available);
            }
        }
        $id = (string) $row['hostid'];
        $this->overrides[$id] = SpeedIntent::overrides($row['macros'] ?? []);
        return ['hostid'=>$id, 'host'=>(string) $row['host'], 'name'=>(string) $row['name'],
            'domain'=>count($domains) === 1 ? (string) array_key_first($domains) : '',
            'management_addresses'=>$this->addresses($addresses), 'dashboard_url'=>Navigation::dashboard($id),
            'explorer_url'=>Navigation::explorer($id), 'snmp_available'=>$available];
    }

    private function addresses(array $addresses): array {
        $result = [];
        foreach ($addresses as $address) {
            $value = is_array($address) ? ($address['address'] ?? $address['value'] ?? null) : $address;
            if (is_string($value) && filter_var($value, FILTER_VALIDATE_IP)) {
                $result[$value] = true;
            }
        }
        return array_keys($result);
    }
}
