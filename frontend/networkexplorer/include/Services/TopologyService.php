<?php

declare(strict_types=1);

namespace Modules\NetworkExplorer\Services;

/** Builds a current graph without hidden-host lookups or an authoritative topology database. */
final class TopologyService {

    public function build(array $hosts, array $datasets): array {
        $resolver = new IdentityResolver($hosts, $datasets);
        $edges = [];
        $findings = [];
        $unresolvedOrdinals = [];
        foreach ($hosts as $key => $host) {
            if (!is_array($host)) {
                continue;
            }
            $hostid = (string) ($host['hostid'] ?? $key);
            $dataset = $datasets[$hostid]['lldp'] ?? [];
            foreach (IdentityResolver::rows($dataset) as $row) {
                if (!is_array($row)) {
                    continue;
                }
                $localPort = is_array($row['local_port_id'] ?? null) ? $row['local_port_id'] : [];
                $local = $resolver->resolveInterface($hostid, $localPort,
                    isset($row['local_interface_uid']) ? (string) $row['local_interface_uid'] : null);
                $source = $this->endpoint($hostid, $local);
                $resolution = $resolver->resolve($row, $hostid);
                $remote = null;
                if ($resolution['status'] === 'resolved' && $resolution['interface_uid'] !== null) {
                    $remote = $resolver->interfaceByUid($resolution['hostid'], $resolution['interface_uid']);
                }
                $target = $resolution['status'] === 'resolved'
                    ? $this->endpoint($resolution['hostid'], $remote)
                    : ['hostid' => null, 'interface_uid' => null, 'if_index' => null,
                        'uid' => null, 'name' => $resolution['status'] === 'ambiguous' ? 'Ambiguous peer' : 'Unresolved peer'];
                $sourceKey = $this->endpointKey($source, $localPort);
                $remotePort = is_array($row['remote_port_id'] ?? null) ? $row['remote_port_id'] : [];
                if ($target['hostid'] === null) {
                    // Even hashes of restricted low-entropy peer IDs permit dictionary attacks.
                    // Unresolved keys use only the permitted local endpoint and row ordinal.
                    $ordinal = ($unresolvedOrdinals[$hostid][$sourceKey] ?? 0) + 1;
                    $unresolvedOrdinals[$hostid][$sourceKey] = $ordinal;
                    $targetKey = 'unresolved:' . $hostid . ':' . $sourceKey . ':' . $ordinal;
                }
                else {
                    $targetKey = $this->endpointKey($target, $remotePort);
                }
                $direction = $sourceKey . '>' . $targetKey;
                $canonical = [$sourceKey, $targetKey];
                sort($canonical, SORT_STRING);
                $edgeid = 'edge-' . substr(hash('sha256', implode('|', $canonical)), 0, 24);
                // Canonical order permits a reciprocal observation to reconcile the same endpoint pair.
                if ($sourceKey > $targetKey) {
                    [$source, $target] = [$target, $source];
                }
                $freshness = $this->freshness($row['freshness'] ?? $dataset['freshness'] ?? 'unknown');
                if (!isset($edges[$edgeid])) {
                    $edges[$edgeid] = [
                        'id' => $edgeid,
                        'source' => $source['hostid'],
                        'target' => $target['hostid'],
                        'source_uid' => $source['interface_uid'],
                        'target_uid' => $target['interface_uid'],
                        'source_endpoint' => $source,
                        'target_endpoint' => $target,
                        'status' => $resolution['status'] === 'resolved' ? 'one_sided' : $resolution['status'],
                        'confirmation' => 'one_sided',
                        'confidence' => $resolution['status'] === 'resolved' ? 'medium' : 'low',
                        'freshness' => $freshness,
                        'observations' => [],
                        'lag_ids' => [],
                        '_directions' => []
                    ];
                }
                $edge = &$edges[$edgeid];
                $edge['_directions'][$direction] = true;
                $observation = [
                    'hostid' => $hostid,
                    'local_interface_uid' => $local === null ? null : (string) $local['uid'],
                    'resolution' => $resolution['status'],
                    'evidence' => $resolution['evidence'],
                    'freshness' => $freshness
                ];
                $observedAt = $row['observed_at'] ?? $dataset['observed_at'] ?? null;
                if (is_string($observedAt)) {
                    $observation['observed_at'] = $observedAt;
                }
                if (!in_array($observation, $edge['observations'], true)) {
                    $edge['observations'][] = $observation;
                }
                $edge['freshness'] = $this->worstFreshness($edge['freshness'], $freshness);
                if ($resolution['status'] === 'resolved' && $hostid === $resolution['hostid']) {
                    $edge['status'] = 'self_link';
                    $this->finding($findings, 'self_link', $edgeid, $hostid,
                        'LLDP identifies an interface on the same monitored host.');
                }
                elseif (count($edge['_directions']) > 1 && $edge['source_uid'] !== null && $edge['target_uid'] !== null) {
                    $edge['confirmation'] = 'bidirectional';
                    $edge['status'] = 'bidirectional';
                    $edge['confidence'] = 'high';
                }
                if ($resolution['status'] !== 'resolved') {
                    $edge['candidate_count'] = $resolution['candidate_count'];
                    $this->finding($findings, $resolution['status'] . '_lldp', $edgeid, $hostid,
                        $resolution['status'] === 'ambiguous'
                            ? 'Peer identity is ambiguous within the permitted routing domain.'
                            : 'Peer identity could not be resolved within the permitted routing domain.');
                }
                elseif ($remote === null) {
                    $this->finding($findings, 'unmapped_remote_port', $edgeid, $hostid,
                        'The monitored peer was identified but its interface mapping is unknown.');
                }
                if ($local === null) {
                    $this->finding($findings, 'unmapped_local_port', $edgeid, $hostid,
                        'The local LLDP port has no unique interface mapping.');
                }
                unset($edge);
            }
        }
        $lags = $this->groupLags($hosts, $datasets, $resolver, $edges);
        foreach ($edges as &$edge) {
            unset($edge['_directions']);
        }
        unset($edge);
        ksort($edges, SORT_STRING);
        ksort($lags, SORT_STRING);
        ksort($findings, SORT_STRING);
        return ['edges' => array_values($edges), 'lags' => array_values($lags), 'findings' => array_values($findings)];
    }

    private function groupLags(array $hosts, array $datasets, IdentityResolver $resolver, array &$edges): array {
        $groups = [];
        $edgeIndex = [];
        foreach ($edges as $edgeid => $edge) {
            foreach (['source', 'target'] as $side) {
                if ($edge[$side] !== null && $edge[$side . '_uid'] !== null) {
                    $edgeIndex[$edge[$side]][$edge[$side . '_uid']][$edgeid] = true;
                }
            }
        }
        foreach ($hosts as $key => $host) {
            if (!is_array($host)) {
                continue;
            }
            $hostid = (string) ($host['hostid'] ?? $key);
            foreach (IdentityResolver::rows($datasets[$hostid]['lag'] ?? []) as $row) {
                if (!is_array($row)) {
                    continue;
                }
                $uid = (string) ($row['interface_uid'] ?? $row['uid'] ?? '');
                $aggregator = (string) ($row['aggregator_id'] ?? $uid);
                if ($uid === '' && $aggregator === '') {
                    continue;
                }
                $id = 'lag-' . substr(hash('sha256', $hostid . '|' . $aggregator . '|' . $uid), 0, 24);
                $group = [
                    'id' => $id,
                    'hostid' => $hostid,
                    'interface_uid' => $uid === '' ? null : $uid,
                    'aggregator_id' => $aggregator,
                    'if_index' => $row['if_index'] ?? null,
                    'name' => (string) ($row['name'] ?? $uid ?: $aggregator),
                    'oper_status' => $row['oper_status'] ?? null,
                    'mode' => in_array($row['mode'] ?? null, ['lacp', 'static', 'pagp'], true) ? $row['mode'] : 'unknown',
                    'freshness' => $this->freshness($datasets[$hostid]['lag']['freshness'] ?? 'unknown'),
                    'members' => [],
                    'edge_ids' => [],
                    'peer_hostids' => [],
                    'multi_chassis' => false
                ];
                foreach (($row['members'] ?? $row['member_interface_uids'] ?? $row['member_uids'] ?? []) as $member) {
                    if (is_string($member) || is_int($member)) {
                        $member = ['interface_uid' => (string) $member];
                    }
                    if (!is_array($member)) {
                        continue;
                    }
                    $memberUid = (string) ($member['interface_uid'] ?? $member['uid'] ?? '');
                    if ($memberUid === '') {
                        continue;
                    }
                    $interface = $resolver->interfaceByUid($hostid, $memberUid);
                    $entry = $this->endpoint($hostid, $interface);
                    $entry['interface_uid'] = $memberUid;
                    $entry['uid'] = $memberUid;
                    $entry['edge_ids'] = [];
                    foreach (['operational', 'selected', 'distributing', 'collecting', 'state'] as $field) {
                        if (array_key_exists($field, $member)) {
                            $entry[$field] = $member[$field];
                        }
                    }
                    foreach (array_keys($edgeIndex[$hostid][$memberUid] ?? []) as $edgeid) {
                        $edge = &$edges[$edgeid];
                        $sourceMatch = $edge['source'] === $hostid && $edge['source_uid'] === $memberUid;
                        $targetMatch = $edge['target'] === $hostid && $edge['target_uid'] === $memberUid;
                        if (!$sourceMatch && !$targetMatch) {
                            continue;
                        }
                        $entry['edge_ids'][] = $edge['id'];
                        $group['edge_ids'][] = $edge['id'];
                        $peer = $sourceMatch ? $edge['target'] : $edge['source'];
                        if ($peer !== null && $peer !== $hostid) {
                            $group['peer_hostids'][] = $peer;
                        }
                        $edge['lag_ids'][] = $id;
                        $edge['lag_ids'] = array_values(array_unique($edge['lag_ids']));
                        $edge['lag_id'] = $edge['lag_ids'][0];
                    }
                    unset($edge);
                    $group['members'][] = $entry;
                }
                $group['edge_ids'] = array_values(array_unique($group['edge_ids']));
                $group['peer_hostids'] = array_values(array_unique($group['peer_hostids']));
                sort($group['edge_ids'], SORT_STRING);
                sort($group['peer_hostids'], SORT_STRING);
                $group['multi_chassis'] = count($group['peer_hostids']) > 1;
                $groups[$id] = $group;
            }
        }
        return $groups;
    }

    private function endpoint(string $hostid, ?array $interface): array {
        return [
            'hostid' => $hostid,
            'interface_uid' => $interface === null ? null : (string) $interface['uid'],
            'uid' => $interface === null ? null : (string) $interface['uid'],
            'if_index' => $interface['if_index'] ?? null,
            'name' => $interface['name'] ?? 'Unknown interface'
        ];
    }

    private function endpointKey(array $endpoint, array $port): string {
        return ($endpoint['hostid'] ?? 'unknown') . ':' . ($endpoint['interface_uid']
            ?? 'unmapped-' . hash('sha256', json_encode($port, JSON_INVALID_UTF8_SUBSTITUTE)));
    }

    private function freshness($value): string {
        return in_array($value, ['current', 'stale', 'unknown'], true) ? $value : 'unknown';
    }

    private function worstFreshness(string $a, string $b): string {
        if ($a === 'stale' || $b === 'stale') {
            return 'stale';
        }
        return $a === 'unknown' || $b === 'unknown' ? 'unknown' : 'current';
    }

    private function finding(array &$findings, string $type, string $edgeid, string $hostid, string $message): void {
        $id = $type . ':' . $edgeid . ':' . $hostid;
        $findings[$id] = [
            'id' => $id,
            'type' => $type,
            'rule' => $type,
            'title' => ucfirst(str_replace('_', ' ', $type)),
            'reason' => $message,
            'severity' => 'info',
            'hostid' => $hostid,
            'edge_id' => $edgeid,
            'message' => $message
        ];
    }
}
