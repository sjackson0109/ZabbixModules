<?php

declare(strict_types=1);

require_once __DIR__ . '/../../frontend/networkexplorer/include/Services/IdentityResolver.php';
require_once __DIR__ . '/../../frontend/networkexplorer/include/Services/TopologyService.php';
require_once __DIR__ . '/../../frontend/networkexplorer/include/Services/SubnetService.php';

use Modules\NetworkExplorer\Services\IdentityResolver;
use Modules\NetworkExplorer\Services\TopologyService;
use Modules\NetworkExplorer\Services\SubnetService;

$checks = 0;
$assert = static function (bool $condition, string $message) use (&$checks): void {
    $checks++;
    if (!$condition) {
        throw new RuntimeException($message);
    }
};
$hosts = [];
foreach (['1' => 'site-a', '2' => 'site-a', '3' => 'site-a', '4' => 'site-b', '5' => ''] as $id => $domain) {
    $hosts[$id] = ['hostid' => (string) $id, 'host' => "switch-$id", 'name' => "Switch $id", 'domain' => $domain];
}
$dataset = static fn(array $data): array => ['data' => $data, 'observed_at' => '2026-10-06T12:00:00Z', 'freshness' => 'current'];
$device = static fn(string $mac, string $address): array => [
    'chassis_ids' => [['subtype' => 4, 'value' => $mac]], 'management_addresses' => [$address]
];
$interface = static fn(string $uid, string $name, int $index): array => [
    'uid' => $uid, 'name' => $name, 'if_index' => $index, 'mac_address' => '02:00:00:00:00:' . sprintf('%02x', $index)
];
$datasets = [
    '1' => ['device' => $dataset([$device('02:00:00:00:01:00', '192.0.2.1')]),
        'interfaces' => $dataset([$interface('a1', 'Gi1', 11), $interface('a2', 'Gi2', 12)])],
    '2' => ['device' => $dataset([$device('02:00:00:00:02:00', '192.0.2.2')]),
        'interfaces' => $dataset([$interface('b1', 'Gi1', 21), $interface('b2', 'Gi2', 22)])],
    '3' => ['device' => $dataset([$device('02:00:00:00:03:00', '192.0.2.3')]),
        'interfaces' => $dataset([$interface('c1', 'Gi1', 31)])],
    '4' => ['device' => $dataset([$device('02:00:00:00:02:00', '192.0.2.2')]),
        'interfaces' => $dataset([$interface('x1', 'Gi1', 21)])],
    '5' => ['device' => $dataset([$device('02:00:00:00:05:00', '192.0.2.5')]), 'interfaces' => $dataset([])]
];
$observation = static fn(string $local, string $mac, string $port): array => [
    'local_interface_uid' => $local, 'local_port_id' => ['subtype' => 5, 'value' => 'Gi1'],
    'remote_chassis_id' => ['subtype' => 4, 'value' => $mac],
    'remote_port_id' => ['subtype' => 5, 'value' => $port],
    'remote_system_name' => null, 'remote_management_addresses' => []
];
$toB = $observation('a1', '02-00-00-00-02-00', 'Gi1');
$resolver = new IdentityResolver($hosts, $datasets);
$result = $resolver->resolve($toB, '1');
$assert($result['hostid'] === '2' && $result['interface_uid'] === 'b1', 'MAC normalization/domain isolation.');
$assert($resolver->resolve($toB, '5')['status'] === 'unresolved', 'Missing domain cannot resolve.');
$assert($resolver->resolve(['remote_system_name' => 'switch-2'], '1')['status'] === 'unresolved', 'Name-only matching is unsafe.');
$addressMatch = $resolver->resolve(['remote_management_addresses' => ['192.0.2.2']], '1');
$assert($addressMatch['status'] === 'resolved' && $addressMatch['hostid'] === '2', 'Unique addresses resolve only in the same domain.');
$assert($resolver->resolve(['remote_chassis_id' => ['subtype' => 7, 'value' => '02:00:00:00:02:00']], '1')['status'] === 'unresolved',
    'Chassis subtypes must not be merged.');
$numeric = array_replace($toB, ['remote_port_id' => ['subtype' => 7, 'value' => '22']]);
$assert($resolver->resolve($numeric, '1')['interface_uid'] === null, 'Numeric local ID is not implicitly ifIndex.');
$numeric['remote_if_index'] = 22;
$assert($resolver->resolve($numeric, '1')['interface_uid'] === 'b2', 'Explicit adapter ifIndex mapping.');
$conflict = array_replace($toB, ['remote_management_addresses' => ['192.0.2.3']]);
$assert($resolver->resolve($conflict, '1')['status'] === 'ambiguous', 'Conflicting identity must remain ambiguous.');
$ambiguousDatasets = $datasets;
$ambiguousDatasets['3']['device'] = $datasets['2']['device'];
$ambiguous = (new IdentityResolver($hosts, $ambiguousDatasets))->resolve($toB, '1');
$assert($ambiguous['status'] === 'ambiguous' && $ambiguous['candidate_count'] === 2, 'Duplicate chassis ambiguity.');
$private = ['remote_system_name' => 'private-secret-peer', 'remote_management_addresses' => ['198.51.100.199']];
$assert(strpos(json_encode($resolver->resolve($private, '1')), 'private-secret-peer') === false, 'Unresolved identity redaction.');

$datasets['1']['lldp'] = $dataset([$toB, $observation('a2', '02:00:00:00:02:00', 'Gi2')]);
$datasets['2']['lldp'] = $dataset([$observation('b1', '02:00:00:00:01:00', 'Gi1')]);
$datasets['2']['lldp']['freshness'] = 'stale';
$topology = (new TopologyService())->build($hosts, $datasets);
$assert(count($topology['edges']) === 2, 'Parallel links must remain separate.');
$confirmed = array_values(array_filter($topology['edges'], static fn(array $edge): bool => $edge['status'] === 'bidirectional'));
$assert(count($confirmed) === 1, 'Reciprocal observations reconcile one edge.');
$assert($confirmed[0]['freshness'] === 'stale', 'Stale reciprocal evidence stays stale.');
$assert($confirmed[0]['source_endpoint']['if_index'] === 11, 'Current ifIndex preserved in endpoint.');
$datasets['1']['lag'] = $dataset([['uid' => 'lag-a', 'member_interface_uids' => ['a1', 'a2']]]);
$datasets['1']['lldp']['data'][1] = $observation('a2', '02:00:00:00:03:00', 'Gi1');
$grouped = (new TopologyService())->build($hosts, $datasets);
$assert(count($grouped['edges']) === 2 && count($grouped['lags']) === 1, 'LAG preserves member edges.');
$assert($grouped['lags'][0]['multi_chassis'] && $grouped['lags'][0]['peer_hostids'] === ['2', '3'], 'Multi-chassis peers retained.');
$assert(count($grouped['lags'][0]['members']) === 2 && count($grouped['lags'][0]['edge_ids']) === 2, 'LAG member edge refs retained.');
$datasets['1']['lldp']['data'][] = array_merge($private, ['local_interface_uid' => 'a2']);
$redacted = (new TopologyService())->build($hosts, $datasets);
$assert(strpos(json_encode($redacted), 'private-secret-peer') === false && strpos(json_encode($redacted), '198.51.100.199') === false,
    'Inaccessible remote identities cannot leak through topology.');
$opaqueBefore = array_values(array_filter($redacted['edges'], static fn(array $edge): bool => $edge['status'] === 'unresolved'))[0]['id'];
$datasets['1']['lldp']['data'][2]['remote_chassis_id'] = ['subtype' => 7, 'value' => 'different-private-secret'];
$datasets['1']['lldp']['data'][2]['remote_port_id'] = ['subtype' => 7, 'value' => 'different-private-port'];
$differentRemote = (new TopologyService())->build($hosts, $datasets);
$opaqueAfter = array_values(array_filter($differentRemote['edges'], static fn(array $edge): bool => $edge['status'] === 'unresolved'))[0]['id'];
$assert($opaqueBefore === $opaqueAfter, 'Unresolved edge identifiers must be independent of restricted peer values.');
$selfDatasets = $datasets;
$selfDatasets['1']['lldp'] = $dataset([$observation('a1', '02:00:00:00:01:00', 'Gi2')]);
$selfGraph = (new TopologyService())->build($hosts, $selfDatasets);
$selfEdges = array_filter($selfGraph['edges'], static fn(array $edge): bool => $edge['status'] === 'self_link');
$assert(count($selfEdges) === 1, 'Self-links must be retained and marked explicitly.');

$portConflict = array_replace($toB, ['remote_if_index' => 22]);
$assert($resolver->resolve($portConflict, '1')['interface_uid'] === null, 'Conflicting explicit port mapping must remain unknown.');

$subnet = new SubnetService();
$assert($subnet->contains('192.0.2.127', '192.0.2.0/25') && !$subnet->contains('192.0.2.128', '192.0.2.0/25'), 'IPv4 bit prefix.');
$assert($subnet->contains('2001:db8::7fff:ffff:ffff:fffe', '2001:db8::/65')
    && !$subnet->contains('2001:db8::8000:0:0:0', '2001:db8::/65'), 'IPv6 bit prefix.');
$assert($subnet->contains('203.0.113.1', '0.0.0.0/0') && !$subnet->contains('::1', '0.0.0.0/0'), 'Zero prefix/family mismatch.');
$assert($subnet->contains('::1', '::1/128') && !$subnet->contains('::2', '::1/128'), 'Exact IPv6 address.');
$assert(!$subnet->validate('192.0.2.0/33') && !$subnet->validate('::/129') && !$subnet->validate('example.test/24')
    && !$subnet->validate('192.0.2.0/-1'), 'Invalid CIDR rejection.');
$annotation = $subnet->annotate(['192.0.2.1', '198.51.100.1'], ['192.0.2.0/24']);
$assert($annotation['status'] === 'mixed' && $annotation['addresses'][1]['state'] === 'outside', 'Out-of-subnet annotation.');
$assert($subnet->annotate([], ['192.0.2.0/24'])['status'] === 'unknown', 'Missing addresses are unknown.');
echo "Topology and subnet checks passed ($checks checks).\n";
