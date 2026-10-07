<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Shared, permission-aware application layer for every widget, page and export. */
final class NetworkService {
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
        $hostids = array_values(array_unique(array_map('strval', $hostids)));
        foreach ($hostids as $id) {
            if (!preg_match('/^[1-9][0-9]*$/D', $id)) {
                throw new \InvalidArgumentException('invalid_hostid');
            }
        }
        if (count($hostids) > 300) {
            throw new \InvalidArgumentException('host_budget_exceeded');
        }
        if (strlen($managementCidr) > 2048) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $cidrs = trim($managementCidr) === '' ? [] : preg_split('/[\s,]+/', trim($managementCidr));
        if (count($cidrs) > 32) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $subnet = new SubnetService();
        foreach ($cidrs as $cidr) {
            if (!$subnet->validate($cidr)) {
                throw new \InvalidArgumentException('invalid_management_cidr');
            }
        }
        $seeds = $hostids ? $this->gateway->hosts($hostids) : [];
        $rows = $this->gateway->hosts();
        $truncated = count($rows) > 300;
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
            if (count($hosts) >= 300 && !isset($hosts[$host['hostid']])) {
                $truncated = true;
                continue;
            }
            $hosts[$host['hostid']] = $host;
        }
        // An inaccessible seed never turns into an all-host request.
        if ($hostids && !$seeds) {
            $hosts = [];
        }
        $read = (new DatasetReader($this->gateway, $this->now))->read($hosts);
        // Hosts without any Network Explorer item (servers, other devices) are not part of the network view,
        // unless explicitly selected.
        $seedIds = array_fill_keys(array_map('strval', array_column($seeds, 'hostid')), true);
        $hosts = array_filter($hosts, static fn($host) => isset($read['collected'][$host['hostid']])
            || isset($seedIds[$host['hostid']]));
        $read['quality'] = array_values(array_filter($read['quality'], static fn($row) => isset($hosts[$row['hostid']])));
        $datasets = $read['datasets'];
        $qualityIndex = [];
        foreach ($read['quality'] as $quality) {
            $qualityIndex[$quality['hostid']][$quality['dataset']] = $quality;
        }
        $interfaces = [];
        $findings = [];
        $policy = new PortPolicy();
        $vlanPorts = [];
        $lldpByUid = [];
        $stpBridges = [];
        $stpPorts = [];
        foreach ($hosts as $hostid => &$host) {
            $capabilities = [];
            foreach (($datasets[$hostid]['port_capability']['data'] ?? []) as $row) {
                $capabilities[$row['uid']] = $row;
            }
            foreach (($datasets[$hostid]['lldp']['data'] ?? []) as $row) {
                // One neighbour per port is the normal case; several make the peer's capability ambiguous.
                $uid = $row['local_interface_uid'] ?? null;
                if (is_string($uid)) {
                    $lldpByUid[$hostid][$uid] = isset($lldpByUid[$hostid][$uid]) ? [] : $row;
                }
            }
            $host['vlans'] = null;
            if (isset($datasets[$hostid]['vlan'])) {
                $host['vlans'] = [];
                foreach ($datasets[$hostid]['vlan']['data'] as $row) {
                    if ($row['kind'] === 'vlan') {
                        $host['vlans'][] = ['vlan_id'=>$row['vlan_id'], 'name'=>$row['name'] ?? null];
                    }
                    else {
                        $vlanPorts[$hostid][$row['interface_uid']] = VlanService::port($row);
                    }
                }
            }
            $host['stp'] = null;
            if (isset($datasets[$hostid]['stp'])) {
                [$host['stp'], $stpPorts[$hostid]] = StpService::split($datasets[$hostid]['stp']['data']);
                $stpBridges[$hostid] = $host['stp'];
            }
            $device = $datasets[$hostid]['device']['data'][0] ?? [];
            foreach (['vendor','model','firmware','hostname'] as $field) {
                $host[$field] = is_string($device[$field] ?? null) ? $device[$field] : null;
            }
            $deviceAddresses = $device['management_addresses'] ?? [];
            $host['management_addresses'] = $this->addresses(array_merge($host['management_addresses'], $deviceAddresses));
            $host['addressing'] = $subnet->annotate($host['management_addresses'], $cidrs);
            $host['out_of_subnet'] = in_array($host['addressing']['status'], ['outside','mixed'], true);
            if ($host['domain'] === '') {
                $findings[] = $this->finding((string) $hostid, null, 'domain_unknown','info',
                    'Matching domain is unknown.', 'Assign a provisioner-controlled ne.domain host tag before peer matching.');
            }
            foreach (($datasets[$hostid]['interfaces']['data'] ?? []) as $row) {
                $output = array_intersect_key($row, array_flip(['uid','if_index','name','description','alias','type',
                    'physical','admin_status','oper_status','speed_bps','duplex','mtu','mac_address',
                    'expected_speed_bps','member','slot','port']));
                $output['hostid'] = (string) $hostid;
                $lldp = $lldpByUid[$hostid][$row['uid']] ?? null;
                $capability = $capabilities[$row['uid']] ?? null;
                [$row['expected_speed_bps'], $row['expected_speed_source'], $basis] = SpeedIntent::derive($row,
                    $capability, $lldp ?: null, $this->overrides[$hostid] ?? []);
                $row['peer_duplex'] = $lldp['remote_duplex'] ?? null;
                $output['expected_speed_basis'] = $basis;
                $output['capability'] = $capability === null ? null : array_intersect_key($capability,
                    array_flip(['autoneg_enabled','oper_speed_bps','oper_duplex','supported_speeds_bps',
                        'advertised_speeds_bps','partner_advertised_speeds_bps']));
                $output['vlan'] = $vlanPorts[$hostid][$row['uid']] ?? null;
                $output['stp'] = $stpPorts[$hostid][$row['uid']] ?? [];
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
                $output['dashboard_url'] = Navigation::dashboard((string) $hostid, $row['uid']);
                $output['explorer_url'] = Navigation::explorer((string) $hostid, $row['uid']);
                $output['peers'] = [];
                if ($evaluation['speed_degraded']) {
                    $findings[] = $this->finding((string) $hostid, $row['uid'], 'speed_below_intent',
                        $evaluation['speed_warning_confirmed'] ? 'warning' : 'info',
                        'Speed below intended value.', $evaluation['reason']);
                }
                if ($evaluation['duplex_mismatch']) {
                    $findings[] = $this->finding((string) $hostid, $row['uid'], 'duplex_mismatch', 'warning',
                        'Duplex mismatch.', 'Half duplex against a full-duplex peer (from LLDP).');
                }
                $interfaces[] = $output;
                if (count($interfaces) > 30000) {
                    throw new \RuntimeException('interface_budget_exceeded');
                }
            }
        }
        unset($host);
        // A bridge ID embeds the bridge's MAC address, so one belonging to no permitted host is replaced by an
        // opaque token: equal IDs stay equal within this response, and nothing identifies the hidden bridge.
        $visibleBridges = [];
        foreach ($stpBridges as $rows) {
            foreach ($rows as $row) {
                $visibleBridges[substr((string) ($row['bridge_id'] ?? ''), 4)] = true;
            }
        }
        $salt = random_bytes(16);
        $mask = static fn($id) => !is_string($id) || isset($visibleBridges[substr($id, 4)]) ? $id
            : 'undisclosed-'.substr(hash_hmac('sha256', $id, $salt), 0, 8);
        foreach ($stpBridges as $hostid => &$rows) {
            foreach ($rows as &$row) {
                $row['root_bridge_id'] = $mask($row['root_bridge_id'] ?? null);
            }
            unset($row);
            $hosts[$hostid]['stp'] = $rows;
        }
        unset($rows);
        foreach ($stpPorts as &$byUid) {
            foreach ($byUid as &$rows) {
                foreach ($rows as &$row) {
                    $row['designated_bridge'] = $mask($row['designated_bridge'] ?? null);
                }
                unset($row);
            }
            unset($rows);
        }
        unset($byUid);
        foreach ($interfaces as &$interface) {
            $interface['stp'] = $stpPorts[$interface['hostid']][$interface['uid']] ?? [];
        }
        unset($interface);
        $graph = (new TopologyService())->build($hosts, $datasets);
        foreach ($graph['edges'] as &$edge) {
            foreach (['source','target'] as $side) {
                $id = $edge[$side] ?? null;
                $uid = $edge[$side.'_uid'] ?? null;
                if ($id !== null && isset($hosts[(string) $id])) {
                    $edge[$side.'_dashboard_url'] = Navigation::dashboard((string) $id,
                        EnvelopeValidator::validUid($uid) ? $uid : null);
                }
            }
        }
        unset($edge);
        // VLAN and STP state belongs to the aggregator's bridge port; LAG members carry what their aggregator carries.
        $viaLag = [];
        foreach ($graph['lags'] as $lag) {
            $hostid = (string) $lag['hostid'];
            $aggregator = $lag['interface_uid'] ?? null;
            foreach ($lag['members'] as $member) {
                $uid = $member['interface_uid'] ?? null;
                if ($aggregator === null || $uid === null) {
                    continue;
                }
                if (!isset($vlanPorts[$hostid][$uid]) && isset($vlanPorts[$hostid][$aggregator])) {
                    $vlanPorts[$hostid][$uid] = $vlanPorts[$hostid][$aggregator] + ['via_lag'=>$lag['name'] ?? $aggregator];
                    $viaLag[$hostid][$uid] = true;
                }
                if (!isset($stpPorts[$hostid][$uid]) && isset($stpPorts[$hostid][$aggregator])) {
                    $stpPorts[$hostid][$uid] = array_map(static fn($row) => $row + ['via_lag'=>$lag['name'] ?? $aggregator],
                        $stpPorts[$hostid][$aggregator]);
                    $viaLag[$hostid][$uid] = true;
                }
            }
        }
        foreach ($interfaces as &$interface) {
            if (isset($viaLag[$interface['hostid']][$interface['uid']])) {
                $interface['vlan'] = $vlanPorts[$interface['hostid']][$interface['uid']] ?? null;
                $interface['stp'] = $stpPorts[$interface['hostid']][$interface['uid']] ?? [];
            }
        }
        unset($interface);
        $labels = [];
        foreach ($interfaces as $interface) {
            $labels[$interface['hostid']][$interface['uid']] = $hosts[$interface['hostid']]['name'].' '.($interface['name'] ?? $interface['uid']);
        }
        $findings = array_merge($findings, VlanService::link($graph['edges'], $vlanPorts, array_map('array_filter', $lldpByUid), $labels),
            StpService::link($graph['edges'], $stpBridges, $stpPorts, array_column($hosts, 'domain', 'hostid')));
        $adjacency = [];
        foreach ($graph['edges'] as $edge) {
            foreach (['source'=>'target','target'=>'source'] as $localSide => $side) {
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
        foreach ($hosts as $hostid => $host) {
            if ($host['snmp_available'] === false) {
                $findings[] = $this->finding((string) $hostid, null, 'snmp_unreachable', 'warning',
                    'SNMP agent is unreachable.', 'Zabbix marks the SNMP interface unavailable. Collection has stopped; '
                    .'the last successful observations are shown.');
            }
        }
        foreach ($read['quality'] as $quality) {
            // One unreachable finding per host replaces a collection finding per dataset.
            if ($quality['errors'] === ['agent_unreachable']) {
                continue;
            }
            if ($quality['status'] !== 'ok' || $quality['freshness'] !== 'current') {
                $findings[] = $this->finding($quality['hostid'], null, 'collection_'.$quality['dataset'],
                    $quality['status'] === 'failed' ? 'warning' : 'info',
                    ucfirst($quality['dataset']).' collection requires attention.',
                    'Outcome: '.$quality['status'].'; observation: '.$quality['freshness'].'.');
            }
        }
        if ($truncated) {
            $findings[] = ['id'=>'scope:host_limit', 'hostid'=>null, 'interface_uid'=>null,
                'severity'=>'info','rule'=>'scope_truncated','title'=>'Host scope is bounded.',
                'reason'=>'Only the first 300 permitted hosts were read. Select a narrower host/domain scope.'];
        }
        $findings = array_merge($findings, $graph['findings']);
        if ($hostids) {
            // Resolve against permitted same-domain candidates, then expose one
            // hop from the seed set. Do not recursively add a neighbour's peers.
            $display = [];
            foreach ($seeds as $seed) {
                $display[(string) $seed['hostid']] = true;
            }
            foreach ($graph['edges'] as $edge) {
                if (isset($display[$edge['source'] ?? ''])
                        && in_array((string) ($edge['source'] ?? ''), $hostids, true)
                        && $edge['target'] !== null) {
                    $display[(string) $edge['target']] = true;
                }
                if (isset($display[$edge['target'] ?? ''])
                        && in_array((string) ($edge['target'] ?? ''), $hostids, true)
                        && $edge['source'] !== null) {
                    $display[(string) $edge['source']] = true;
                }
            }
            $hosts = array_intersect_key($hosts, $display);
            $interfaces = array_values(array_filter($interfaces,
                static fn($row) => isset($display[$row['hostid']])));
            $graph['edges'] = array_values(array_filter($graph['edges'], static fn($edge) =>
                ($edge['source'] === null || isset($display[$edge['source']]))
                && ($edge['target'] === null || isset($display[$edge['target']]))));
            $edgeIds = array_fill_keys(array_column($graph['edges'], 'id'), true);
            $graph['lags'] = array_values(array_filter($graph['lags'],
                static fn($row) => isset($display[$row['hostid']])));
            foreach ($graph['lags'] as &$lag) {
                $lag['edge_ids'] = array_values(array_filter($lag['edge_ids'], static fn($id) => isset($edgeIds[$id])));
                $lag['peer_hostids'] = array_values(array_filter($lag['peer_hostids'], static fn($id) => isset($display[$id])));
                foreach ($lag['members'] as &$member) {
                    $member['edge_ids'] = array_values(array_filter($member['edge_ids'], static fn($id) => isset($edgeIds[$id])));
                }
                unset($member);
            }
            unset($lag);
            foreach ($interfaces as &$interface) {
                $interface['peers'] = array_values(array_filter($interface['peers'], static fn($peer) =>
                    $peer['hostid'] === null || isset($display[$peer['hostid']])));
            }
            unset($interface);
            $read['quality'] = array_values(array_filter($read['quality'], static fn($row) => isset($display[$row['hostid']])));
            $findings = array_values(array_filter($findings, static fn($row) =>
                ($row['hostid'] === null || isset($display[$row['hostid']]))
                && (!isset($row['edge_id']) || isset($edgeIds[$row['edge_id']]))));
        }
        return ['schema_version'=>'1.1', 'generated_at'=>gmdate('c', $this->now ?? time()),
            'scope'=>['seed_hostids'=>$hostids, 'management_cidrs'=>$cidrs, 'truncated'=>$truncated,
                'neighbour_hops'=>$hostids ? 1 : 0],
            'hosts'=>array_values($hosts), 'interfaces'=>$interfaces, 'edges'=>$graph['edges'],
            'lags'=>$graph['lags'], 'quality'=>$read['quality'],
            'findings'=>$findings,
            'budgets'=>$read['budgets'] + ($this->gateway instanceof ApiGateway ? $this->gateway->metrics : [])];
    }

    public function selectedInterface(string $hostid, string $uid): ?array {
        if (!EnvelopeValidator::validUid($uid)) {
            return null;
        }
        foreach ($this->build([$hostid])['interfaces'] as $interface) {
            if ($interface['hostid'] === $hostid && $interface['uid'] === $uid) {
                return $interface;
            }
        }
        return null;
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
            if ((int) ($interface['type'] ?? 0) === 2 && (int) ($interface['useip'] ?? 0) === 1) {
                $addresses[] = $interface['ip'];
            }
        }
        // Zabbix marks an SNMP interface unavailable (2) after timeouts; it records no failed value then.
        $available = null;
        foreach ($row['interfaces'] ?? [] as $interface) {
            if ((int) ($interface['type'] ?? 0) === 2 && isset($interface['available'])) {
                $state = (int) $interface['available'];
                $available = $state === 2 ? false : ($state === 1 && $available !== false ? true : $available);
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

    private function finding(string $hostid, ?string $uid, string $rule, string $severity,
            string $title, string $reason): array {
        return ['id'=>hash('sha256', $hostid.'|'.($uid ?? '').'|'.$rule), 'hostid'=>$hostid,
            'interface_uid'=>$uid,'severity'=>$severity,'rule'=>$rule,'title'=>$title,'reason'=>$reason];
    }
}
