<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\NetworkService;

/** The five synthetic lab switches, normalised by the native template JavaScript, read as one network. */
(static function (): void {
    $node = trim((string) shell_exec('command -v node'));
    if ($node === '') {
        echo "Lab fixture network checks skipped: Node is needed to run the template normalisers.\n";
        return;
    }
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $snapshots = ['ne.raw.system'=>'ne.device.snapshot', 'ne.raw.if.inventory'=>'ne.interfaces.inventory',
        'ne.raw.if.state'=>'ne.interfaces.state', 'ne.raw.if.capability'=>'ne.port_capability.snapshot',
        'ne.raw.lldp'=>'ne.lldp.snapshot', 'ne.raw.vlan'=>'ne.vlan.snapshot', 'ne.raw.stp'=>'ne.stp.snapshot',
        'ne.raw.lag'=>'ne.lag.snapshot'];
    $switches = ['sw-core-01'=>['11','10.101.1.10'], 'sw-access-17'=>['12','10.101.2.17'],
        'sw-dist-02'=>['13','10.101.0.2'], 'sw-dist-01'=>['14','10.102.5.10'], 'sw-stack-01'=>['15','10.101.3.1']];
    $gateway = new FixtureGateway();
    $now = 0;
    foreach ($switches as $name => [$id, $address]) {
        $gateway->hostRows[] = ['hostid'=>$id, 'host'=>$name, 'name'=>$name, 'tags'=>[['tag'=>'ne.domain','value'=>'lab']],
            'interfaces'=>[['type'=>2,'useip'=>1,'ip'=>$address,'available'=>1]], 'macros'=>[]];
        foreach ($snapshots as $raw => $key) {
            $json = shell_exec(escapeshellarg($node).' '.escapeshellarg(__DIR__.'/../js/run_normaliser.cjs').' '
                .escapeshellarg($raw).' '.escapeshellarg(__DIR__.'/../fixtures/walks/'.$name.'.snmprec'));
            $envelope = json_decode((string) $json, true);
            $now = max($now, (int) strtotime($envelope['observed_at']));
            $gateway->add($id, $key, [$envelope]);
        }
    }
    $network = (new NetworkService($gateway, $now + 5))->build([], '10.101.0.0/16');
    $hosts = array_column($network['hosts'], null, 'name');
    $names = [];
    foreach ($network['interfaces'] as $row) {
        $names[$row['hostid']][$row['uid']] = $row['name'];
    }
    $link = static function (array $edge) use ($names): string {
        $ends = [$names[$edge['source']][$edge['source_uid']] ?? '?', $names[$edge['target']][$edge['target_uid']] ?? '?'];
        sort($ends);
        return implode(' - ', $ends);
    };
    $edges = [];
    foreach ($network['edges'] as $edge) {
        $edges[$edge['source'].'/'.$edge['target'].' '.$link($edge)] = $edge;
    }

    $assert($hosts['sw-dist-01']['out_of_subnet'] && !$hosts['sw-core-01']['out_of_subnet'],
        'The management subnet flags the connected switch outside it, and keeps it visible.');
    $assert(count($network['edges']) === 6 && !array_filter($network['edges'], static fn($e) => $e['status'] !== 'bidirectional'),
        'All six physical links are confirmed from both ends.');
    $assert($hosts['sw-dist-02']['stp'][0]['is_root'] && !$hosts['sw-core-01']['stp'][0]['is_root'], 'The RSTP root is marked.');

    $lags = array_column($network['lags'], null, 'name');
    $assert(isset($lags['Po1'], $lags['Po10']) && $lags['Po1']['peer_hostids'] === ['13'] && $lags['Po10']['peer_hostids'] === ['11']
        && count($lags['Po1']['edge_ids']) === 2 && $lags['Po1']['edge_ids'] === $lags['Po10']['edge_ids'],
        'Po1 and Po10 are one logical link over both member links, despite different local numbers.');
    foreach (['11/13 Te0/1 - Te1/0/1', '11/13 Te0/2 - Te1/0/2'] as $key) {
        $assert(isset($edges[$key]) && $edges[$key]['vlan']['common'] === '1,49-50' && !$edges[$key]['stp']['blocked'],
            "LAG member link $key carries the aggregator's VLANs and STP state.");
    }
    $assert($edges['11/14 Gi0/1 - Gi1/0/24']['stp']['blocked'] && $edges['11/14 Gi0/1 - Gi1/0/24']['stp']['source']['role'] === 'alternate',
        'The core/distribution triangle blocks at sw-core-01 Gi1/0/24.');
    $assert($edges['13/14 Te0/2 - Te0/3']['vlan']['common'] === '1,49-50', 'The distribution link carries VLANs 1, 49 and 50.');

    $assert($edges['13/15 Te0/4 - Te1/1/1']['vlan']['common'] === '1,49-50' && !$edges['13/15 Te0/4 - Te1/1/1']['stp']['blocked'],
        'The stack uplink carries VLANs 1, 49 and 50 and forwards.');

    // ENTITY-MIB placement and MAU media.
    $ports = [];
    foreach ($network['interfaces'] as $row) {
        $ports[$row['hostid'].' '.$row['name']] = $row;
    }
    $place = static fn(string $key): string => implode('/', array_map(static fn($v) => var_export($v, true),
        [$ports[$key]['member'] ?? null, $ports[$key]['slot'] ?? null, $ports[$key]['port'] ?? null, $ports[$key]['media'] ?? null]));
    $assert($place('15 Gi1/0/24') === "1/0/24/'copper'" && $place('15 Gi2/0/3') === "2/0/3/'copper'"
        && $place('15 Te2/1/2') === "2/1/2/'sfp_plus'", 'Stack ports are placed by member, slot and position: '.$place('15 Te2/1/2'));
    $assert($place('11 Te1/0/2') === "1/1/2/'sfp_plus'" && $place('12 Gi1/0/48') === "1/0/48/'copper'",
        'Single-chassis ports are placed on member 1.');
    $assert($place('13 Te0/1') === "NULL/NULL/NULL/'sfp_plus'", 'Ports without port entities stay unplaced.');
    $devices = array_column($network['hosts'], null, 'name');
    $assert(array_column($devices['sw-stack-01']['stack_members'], 'member') === ['Unit 1', 'Unit 2']
        && $devices['sw-core-01']['stack_members'] === [], 'The stack reports two members; a single chassis none.');

    $rules = array_map(static fn($f) => $f['rule'], $network['findings']);
    sort($rules);
    $assert($rules === ['duplex_mismatch','speed_below_intent','speed_below_intent','vlan_not_carried'],
        'The lab network produces exactly the Appendix A findings: '.implode(', ', $rules));

    // A user who cannot read sw-dist-01 sees an undisclosed peer, never its name, address or chassis.
    $gateway->hostRows = array_values(array_filter($gateway->hostRows, static fn($h) => $h['host'] !== 'sw-dist-01'));
    $gateway->itemRows = array_values(array_filter($gateway->itemRows, static fn($i) => $i['hostid'] !== '14'));
    $restricted = (new NetworkService($gateway, $now + 5))->build([], '10.101.0.0/16');
    $json = json_encode($restricted);
    foreach (['sw-dist-01', '10.102.5.10', '00:11:22:33:44:a1', '0011223344a1'] as $secret) {
        $assert(!str_contains($json, $secret), "Restricted host detail \"$secret\" is absent from the payload.");
    }
    $assert(count($restricted['hosts']) === 4 && count(array_filter($restricted['edges'], static fn($e) => $e['target'] === null
        || $e['source'] === null)) === 2, 'Links to the hidden switch remain as undisclosed placeholders.');

    echo "Lab fixture network checks passed ($checks checks).\n";
})();
