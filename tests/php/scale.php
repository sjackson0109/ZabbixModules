<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\Limits;
use Modules\NetworkExplorer\Services\NetworkScope;
use Modules\NetworkExplorer\Services\NetworkService;

/**
 * Fleet scaling: the display budget (switches drawn) is separate from the identity-candidate budget (hosts peers
 * are resolved against), candidates are found by domain and by Network Explorer items rather than by taking the
 * first hosts returned, and a scope too large to draw says so instead of dropping switches.
 */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = strtotime('2026-10-06T12:00:00Z');
    $envelope = static fn(string $dataset, array $data): array => ['schema_version'=>'1.0', 'dataset'=>$dataset,
        'generation_id'=>'scale-g1', 'attempted_at'=>'2026-10-06T12:00:00Z', 'observed_at'=>'2026-10-06T12:00:00Z',
        'status'=>'ok', 'complete'=>true, 'source'=>['method'=>'fixture', 'adapter'=>'test', 'version'=>'1.0'],
        'capability'=>['state'=>'supported', 'reason'=>null], 'errors'=>[], 'data'=>$data];
    $port = static fn(string $uid): array => ['uid'=>$uid, 'if_index'=>1, 'name'=>$uid, 'physical'=>true,
        'admin_status'=>'up', 'oper_status'=>'up', 'speed_bps'=>1000000000, 'duplex'=>'full'];
    $lldp = static fn(string $local, string $remote): array => ['local_interface_uid'=>'to-'.$remote,
        'local_port_id'=>['subtype'=>5, 'value'=>'to-'.$remote], 'remote_chassis_id'=>['subtype'=>7,
        'value'=>'chassis-'.$remote], 'remote_port_id'=>['subtype'=>5, 'value'=>'to-'.$local],
        'remote_management_addresses'=>[], 'remote_system_name'=>null];
    /** A switch with device, interface and LLDP snapshots; $links are the switches it sees. */
    $switch = static function (FixtureGateway $gateway, int $id, array $tags, array $links = [])
            use ($envelope, $port, $lldp): void {
        $gateway->hostRows[] = ['hostid'=>(string) $id, 'host'=>'sw-'.$id, 'name'=>'Switch '.$id, 'tags'=>$tags,
            'interfaces'=>[['type'=>2, 'useip'=>1, 'ip'=>'10.'.intdiv($id, 65536).'.'.intdiv($id % 65536, 256).'.'.($id % 256)]]];
        $gateway->add((string) $id, 'ne.device.snapshot', [$envelope('device', [['chassis_ids'=>[['subtype'=>7,
            'value'=>'chassis-'.$id]]]])]);
        $gateway->add((string) $id, 'ne.interfaces.state', [$envelope('interfaces',
            array_map(static fn($peer) => $port('to-'.$peer), $links ?: ['none']))]);
        $gateway->add((string) $id, 'ne.lldp.snapshot', [$envelope('lldp',
            array_map(static fn($peer) => $lldp((string) $id, (string) $peer), $links))]);
    };
    $server = static function (FixtureGateway $gateway, int $id, array $tags = []): void {
        $gateway->hostRows[] = ['hostid'=>(string) $id, 'host'=>'srv-'.$id, 'name'=>'Server '.$id, 'tags'=>$tags,
            'interfaces'=>[]];
    };
    $domain = static fn(string $value): array => [['tag'=>'ne.domain', 'value'=>$value]];
    $site = static fn(string $value, string $d): array => [['tag'=>'ne.domain', 'value'=>$d],
        ['tag'=>'site', 'value'=>$value]];
    $ids = static function (array $network): array {
        $ids = array_column($network['hosts'], 'hostid');
        sort($ids);
        return $ids;
    };

    $assert(Limits::DISPLAY_HOSTS === 300 && Limits::CANDIDATE_HOSTS > Limits::DISPLAY_HOSTS,
        'The identity-candidate budget is larger than, and separate from, the display budget.');

    // One domain with 600 switches; the two at site "edge" link to switch 550, far beyond the first 300 host IDs.
    $gateway = new FixtureGateway();
    $switch($gateway, 1, $site('edge', 'big'), [2, 550]);
    $switch($gateway, 2, $site('edge', 'big'), [1]);
    for ($id = 3; $id <= 600; ++$id) {
        $switch($gateway, $id, $domain('big'), $id === 550 ? [1] : []);
    }
    $edge = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create([], '', 'edge'));
    $assert($ids($edge) === ['1', '2', '550'], 'A peer beyond the first 300 hosts in the domain still resolves.');
    $confirmed = array_values(array_filter($edge['edges'], static fn($e) =>
        in_array('550', [$e['source'], $e['target']], true)));
    $assert(count($confirmed) === 1 && $confirmed[0]['confirmation'] === 'bidirectional',
        'The neighbour is read in full, so its own LLDP confirms the link.');
    $assert(!array_filter($edge['findings'], static fn($f) => $f['rule'] === 'identity_candidates_truncated'),
        'A domain within the candidate budget reports no truncation.');
    $full = [];
    foreach ($gateway->itemQueries as $query) {
        if ($query['keys'] === []) {
            $full = array_merge($full, $query['hostids']);
        }
    }
    sort($full);
    $assert($full === ['1', '2', '550'], 'Only drawn switches are read in full; other candidates give identity only.');
    $assert($edge['budgets']['identity_candidates'] === 600, 'All 600 switches in the domain were identity candidates.');

    // The same domain with the switches seeded one at a time behaves the same.
    $seeded = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create(['550']));
    $assert($ids($seeded) === ['1', '550'], 'A seed far down the host list resolves its peers too.');

    // A neighbour seen only from its own side (the drawn switch reports no LLDP for that port) is still found.
    $gateway = new FixtureGateway();
    $switch($gateway, 1, $site('edge', 'd'), []);
    for ($id = 2; $id <= 400; ++$id) {
        $switch($gateway, $id, $domain('d'), $id === 399 ? [1] : []);
    }
    $oneSided = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create([], '', 'edge'));
    $assert($ids($oneSided) === ['1', '399'], 'A neighbour whose own LLDP names the drawn switch is shown.');

    // The fleet counts only Network Explorer hosts, however many other hosts the user can read.
    $gateway = new FixtureGateway();
    for ($id = 1; $id <= 1500; ++$id) {
        $server($gateway, $id);
    }
    for ($id = 1501; $id <= 1750; ++$id) {
        $switch($gateway, $id, $domain('f'), $id < 1750 ? [$id + 1] : []);
    }
    $fleet = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create());
    $assert(count($fleet['hosts']) === 250 && !isset($fleet['scope']['oversized']),
        'All 250 switches are drawn although 1,500 servers sort before them.');

    // Over the display budget: nothing drawn, the count stated, no findings or quality claimed.
    $gateway = new FixtureGateway();
    for ($id = 1; $id <= 320; ++$id) {
        $switch($gateway, $id, $id <= 10 ? $site('small', 'g') : $domain('g'));
    }
    $big = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create([], '', '', '', true));
    $over = $big['scope']['oversized'] ?? null;
    $assert($over !== null && $over['devices'] === 320 && $over['limit'] === 300 && !$over['at_least'],
        'A fleet of 320 switches is reported as oversized with its real count.');
    $assert(str_contains($over['message'], 'This scope contains 320 visible Network Explorer devices.')
        && str_contains($over['message'], 'limited to 300 devices'), 'The message states both numbers.');
    $assert($big['hosts'] === [] && $big['edges'] === [] && $big['findings'] === [] && $big['quality'] === [],
        'An oversized scope draws nothing rather than an arbitrary subset.');
    $assert(count($big['scope']['candidates']) === 320, 'The seed selector still lists the scope to narrow it.');
    $assert(!array_filter($gateway->itemQueries, static fn($q) => $q['keys'] === []),
        'Nothing is read in full for an oversized scope.');
    $small = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create([], '', 'small'));
    $assert(count($small['hosts']) === 10 && !isset($small['scope']['oversized']), 'Narrowing by site draws it.');
    $assert(count((new NetworkService($gateway, $now))->buildScope(NetworkScope::create(['5']))['hosts']) === 1,
        'Narrowing by seed draws it.');

    // A fleet beyond the candidate budget is reported as "more than".
    $gateway = new FixtureGateway();
    for ($id = 1; $id <= Limits::CANDIDATE_HOSTS + 5; ++$id) {
        $gateway->hostRows[] = ['hostid'=>(string) $id, 'host'=>'sw-'.$id, 'name'=>'Switch '.$id, 'tags'=>[]];
        $gateway->add((string) $id, 'ne.device.snapshot', [$envelope('device', [])]);
    }
    $huge = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create());
    $assert($huge['scope']['oversized']['at_least'] && str_contains($huge['scope']['oversized']['message'],
        'more than '.Limits::CANDIDATE_HOSTS), 'A count the budget could not finish is stated as "more than".');
    $filtered = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create([], '', '', 'none'));
    $assert($filtered['hosts'] === [] && !isset($filtered['scope']['oversized']), 'An empty filter is simply empty.');

    // A domain larger than the candidate budget: the seed is drawn, and the bounded identity set is reported.
    $gateway = new FixtureGateway();
    $switch($gateway, 1, $domain('wide'), [2]);
    $switch($gateway, 2, $domain('wide'), [1]);
    for ($id = 3; $id <= Limits::CANDIDATE_HOSTS + 10; ++$id) {
        $gateway->hostRows[] = ['hostid'=>(string) $id, 'host'=>'sw-'.$id, 'name'=>'Switch '.$id, 'tags'=>$domain('wide')];
    }
    $wide = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create(['1']));
    $assert($ids($wide) === ['1', '2'], 'The seed and its neighbour are drawn.');
    $assert((bool) array_filter($wide['findings'], static fn($f) => $f['rule'] === 'identity_candidates_truncated'
        && $f['severity'] === 'warning') && $wide['scope']['candidates_truncated'],
        'A bounded identity set is a finding, never silent.');

    // A seeded neighbourhood that would exceed the display budget is oversized too.
    $gateway = new FixtureGateway();
    $switch($gateway, 1, $domain('star'), range(2, 301));
    for ($id = 2; $id <= 301; ++$id) {
        $switch($gateway, $id, $domain('star'), [1]);
    }
    $star = (new NetworkService($gateway, $now))->buildScope(NetworkScope::create(['1']));
    $assert(($star['scope']['oversized']['devices'] ?? null) === 301 && $star['hosts'] === [],
        'A seed with 300 neighbours is 301 devices: oversized, not cut.');
    echo "Scale checks passed ($checks checks).\n";
})();
