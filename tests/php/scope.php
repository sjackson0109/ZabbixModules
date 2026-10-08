<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\NetworkScope;
use Modules\NetworkExplorer\Services\NetworkService;
use Modules\NetworkExplorer\Services\ReportService;

/** Site, domain and seed scoping of the Explorer page: the same scope for graph, findings, quality and reports. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = strtotime('2026-10-06T12:00:00Z');
    $envelope = static fn(string $dataset, array $data): array => ['schema_version'=>'1.0', 'dataset'=>$dataset,
        'generation_id'=>'scope-g1', 'attempted_at'=>'2026-10-06T12:00:00Z', 'observed_at'=>'2026-10-06T12:00:00Z',
        'status'=>'ok', 'complete'=>true, 'source'=>['method'=>'fixture', 'adapter'=>'test', 'version'=>'1.0'],
        'capability'=>['state'=>'supported', 'reason'=>null], 'errors'=>[], 'data'=>$data];
    $port = static fn(string $uid): array => ['uid'=>$uid, 'if_index'=>1, 'name'=>'Gi1', 'physical'=>true,
        'admin_status'=>'up', 'oper_status'=>'up', 'speed_bps'=>1000000000, 'duplex'=>'full'];
    $lldp = static fn(string $local, string $remote): array => ['local_interface_uid'=>'if-'.$local.'-'.$remote,
        'local_port_id'=>['subtype'=>5, 'value'=>'Gi1'], 'remote_chassis_id'=>['subtype'=>7, 'value'=>'chassis-'.$remote],
        'remote_port_id'=>['subtype'=>5, 'value'=>'Gi1'], 'remote_management_addresses'=>[], 'remote_system_name'=>null];

    // Hosts 1-3 share domain d-a: 1 and 2 at site east, 3 at west. 5 is at east in domain d-b. 6 has two site tags.
    // 4 (site "secret-site") exists but this user cannot read it, so the gateway never returns it.
    $sites = ['1'=>['east'], '2'=>['east'], '3'=>['west'], '5'=>['east'], '6'=>['east', 'west']];
    $domains = ['1'=>'d-a', '2'=>'d-a', '3'=>'d-a', '5'=>'d-b', '6'=>'d-a'];
    $links = ['1'=>['2'], '2'=>['1', '3', '4'], '3'=>['2'], '5'=>[], '6'=>[]];
    $gateway = new FixtureGateway();
    foreach ($sites as $id => $values) {
        $id = (string) $id;
        $tags = [['tag'=>'ne.domain', 'value'=>$domains[$id]]];
        foreach ($values as $value) {
            $tags[] = ['tag'=>'site', 'value'=>$value];
        }
        $gateway->hostRows[] = ['hostid'=>$id, 'host'=>'sw-'.$id, 'name'=>'Switch '.$id, 'tags'=>$tags,
            'interfaces'=>[['type'=>2, 'useip'=>1, 'ip'=>'192.0.2.'.$id]]];
        $gateway->add($id, 'ne.device.snapshot', [$envelope('device', [['chassis_ids'=>[['subtype'=>7,
            'value'=>'chassis-'.$id]], 'management_addresses'=>['192.0.2.'.$id]]])]);
        $gateway->add($id, 'ne.interfaces.state', [$envelope('interfaces',
            array_map(static fn($peer) => $port('if-'.$id.'-'.$peer), $links[$id] ?: ['none']))]);
        $gateway->add($id, 'ne.lldp.snapshot', [$envelope('lldp',
            array_map(static fn($peer) => $lldp($id, $peer), $links[$id]))]);
    }
    $service = static fn() => new NetworkService($gateway, $now);
    $ids = static function (array $network): array {
        $ids = array_column($network['hosts'], 'hostid');
        sort($ids);
        return $ids;
    };
    $byId = static fn(array $network): array => array_column($network['hosts'], null, 'hostid');

    $options = $service()->scopeOptions();
    $assert($options['sites'] === ['east', 'west'] && $options['domains'] === ['d-a', 'd-b'] && !$options['truncated'],
        'Selectors list the site and domain values of readable hosts, and a host with two sites adds neither.');
    $assert(!str_contains(json_encode($options), 'secret-site'), 'A value carried only by an unreadable host is never listed.');

    $fleet = $service()->buildScope(NetworkScope::create());
    $assert($ids($fleet) === ['1', '2', '3', '5', '6'] && $fleet['scope']['neighbour_hops'] === 0,
        'No scope is the whole permitted fleet.');
    $assert($byId($fleet)['1']['site'] === 'east' && $byId($fleet)['6']['site'] === '',
        'A host has a site only when it carries exactly one site tag.');

    $east = $service()->buildScope(NetworkScope::create([], '', 'east', '', true));
    $assert($ids($east) === ['1', '2', '3', '5'], 'A site shows its switches and their permitted direct neighbours.');
    $assert($byId($east)['3']['outside_site'] && !$byId($east)['2']['outside_site'],
        'A connected neighbour at another site stays visible, marked outside the site.');
    $assert(array_column($east['scope']['candidates'], 'hostid') === ['1', '2', '5'],
        'The seed selector lists only the switches inside the filters.');
    $assert($east['scope']['site'] === 'east' && $east['scope']['domain'] === '', 'The response describes its scope.');
    $assert(count(array_filter($east['edges'], static fn($e) => $e['target'] === null)) === 1
        && !str_contains(json_encode($east), 'chassis-4'), 'An unreadable peer stays an undisclosed placeholder.');
    foreach (['quality', 'findings', 'interfaces'] as $part) {
        $assert(!array_diff(array_filter(array_column($east[$part], 'hostid')), $ids($east)),
            ucfirst($part).' follow the same scope as the graph.');
    }
    $reports = new ReportService();
    $assert($ids(['hosts'=>$reports->rows($east, 'inventory')]) === $ids($east),
        'Exports cover the same scope as the graph.');

    $west = $service()->buildScope(NetworkScope::create([], '', 'west'));
    $assert($ids($west) === ['2', '3'] && $byId($west)['2']['outside_site'], 'Each site keeps only its own context.');
    $assert($ids($service()->buildScope(NetworkScope::create([], '', '', 'd-b'))) === ['5'], 'A domain filter narrows.');
    $assert($ids($service()->buildScope(NetworkScope::create([], '', 'east', 'd-b'))) === ['5'],
        'Site and domain filters combine.');
    $assert($service()->buildScope(NetworkScope::create(['3'], '', 'east'))['hosts'] === [],
        'A seed outside the filters never widens into the filtered fleet.');
    $seeded = $service()->buildScope(NetworkScope::create(['1'], '', 'east'));
    $assert($ids($seeded) === ['1', '2'] && $seeded['scope']['seed_hostids'] === ['1'],
        'A seed inside the filters keeps the one-hop neighbourhood.');
    $assert($service()->buildScope(NetworkScope::create([], '', 'nowhere'))['hosts'] === [],
        'An unknown site shows nothing rather than everything.');
    $assert($service()->build(['1']) === $service()->buildScope(NetworkScope::create(['1'])),
        'The widget entry point is the same scoped build.');

    foreach (["east\n", str_repeat('x', 129), "\xff"] as $bad) {
        try {
            NetworkScope::create([], '', $bad);
            throw new RuntimeException('Bad site accepted');
        }
        catch (InvalidArgumentException $e) {
            $assert($e->getMessage() === 'invalid_scope_filter', 'Malformed scope filters are rejected.');
        }
    }
    echo "Scope checks passed ($checks checks).\n";
})();
