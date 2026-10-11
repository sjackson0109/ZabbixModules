<?php
declare(strict_types=1);
/**
 * Reader budget at the spec's scale: 300 switches, 15,000 physical ports, 1,000 links, with VLAN and STP data.
 * Synthetic envelopes in memory; measures NetworkService::build() only (no Zabbix API or history latency).
 * Usage: php -d memory_limit=2G tests/perf/scale.php [runs] [payload.json] [switches] [seed]
 *   (the payload feeds tests/perf/render.cjs). With `seed`, builds one switch's neighbourhood instead of the fleet,
 *   so every other switch in the domain is an identity candidate: e.g. `... 3 /dev/null 1000 seed`.
 */
require __DIR__.'/../php/services.php';

use Modules\NetworkExplorer\Services\NetworkService;

$runs = (int) ($argv[1] ?? 5);
$switches = (int) ($argv[3] ?? 300); $ports = 50; $links = 1000;
$seed = ($argv[4] ?? '') === 'seed' ? ['10001'] : [];
$now = strtotime('2026-10-07T12:00:00Z');
$time = gmdate('Y-m-d\TH:i:s\Z', $now);
$envelope = static fn(string $dataset, array $data) => ['schema_version'=>'1.1','dataset'=>$dataset,'generation_id'=>'perf',
    'attempted_at'=>$time,'observed_at'=>$time,'status'=>'ok','complete'=>true,
    'source'=>['method'=>'native_snmp','adapter'=>'perf','version'=>'1.1.0'],
    'capability'=>['state'=>'supported','reason'=>null],'errors'=>[],'data'=>$data];
$uid = static fn(int $switch, int $port) => sprintf('if-%024x', $switch * 1000 + $port);
$mac = static fn(int $switch) => sprintf('02:00:00:00:%02x:%02x', intdiv($switch, 256), $switch % 256);
// Links: a ring plus chords, each using a distinct free port at both ends.
$next = array_fill(1, $switches, 1);
$edges = [];
for ($i = 0; count($edges) < $links; ++$i) {
    $a = $i % $switches + 1;
    $b = ($a + 1 + intdiv($i, $switches) * 7) % $switches + 1;
    if ($a === $b || $next[$a] > $ports || $next[$b] > $ports) {
        continue;
    }
    $edges[] = [$a, $next[$a]++, $b, $next[$b]++];
}
$lldp = [];
foreach ($edges as [$a, $pa, $b, $pb]) {
    foreach ([[$a, $pa, $b, $pb], [$b, $pb, $a, $pa]] as [$l, $lp, $r, $rp]) {
        $lldp[$l][] = ['local_interface_uid'=>$uid($l, $lp), 'local_port_id'=>['subtype'=>5,'value'=>"Gi$lp"],
            'remote_chassis_id'=>['subtype'=>4,'value'=>$mac($r)], 'remote_port_id'=>['subtype'=>5,'value'=>"Gi$rp"],
            'remote_system_name'=>"sw-$r", 'remote_management_addresses'=>[], 'remote_advertised_speeds_bps'=>[1000000000],
            'remote_duplex'=>'full', 'remote_pvid'=>1, 'capabilities'=>['enabled'=>['bridge']]];
    }
}
$gateway = new FixtureGateway();
for ($s = 1; $s <= $switches; ++$s) {
    $id = (string) (10000 + $s);
    $gateway->hostRows[] = ['hostid'=>$id, 'host'=>"sw-$s", 'name'=>"sw-$s", 'tags'=>[['tag'=>'ne.domain','value'=>'perf']],
        'interfaces'=>[['type'=>2,'useip'=>1,'ip'=>'10.'.intdiv($s, 256).'.'.($s % 256).'.1','available'=>1]], 'macros'=>[]];
    $rows = $caps = $vlan = $stp = [];
    $stp[] = ['kind'=>'bridge','instance'=>0,'protocol'=>'rstp','bridge_id'=>'8000'.str_replace(':', '', $mac($s)),
        'root_bridge_id'=>'1000'.str_replace(':', '', $mac(1)),'root_cost'=>2000,'root_port_uid'=>$uid($s, 1),'priority'=>32768,
        'vlans'=>null,'topology_changes'=>1,'time_since_topology_change_s'=>86400];
    for ($p = 1; $p <= $ports; ++$p) {
        $rows[] = ['uid'=>$uid($s, $p),'if_index'=>$p,'name'=>"Gi$p",'description'=>"Port $p",'alias'=>null,'type'=>6,'physical'=>true,
            'admin_status'=>'up','oper_status'=>$p % 5 ? 'up' : 'down','speed_bps'=>1000000000,'duplex'=>'full','mtu'=>1500,
            'mac_address'=>null,'member'=>1,'slot'=>0,'port'=>$p];
        $caps[] = ['uid'=>$uid($s, $p),'autoneg_enabled'=>true,'oper_speed_bps'=>1000000000,'oper_duplex'=>'full',
            'supported_speeds_bps'=>[100000000,1000000000],'advertised_speeds_bps'=>[100000000,1000000000],'partner_advertised_speeds_bps'=>null];
        $vlan[] = ['kind'=>'port','interface_uid'=>$uid($s, $p),'mode'=>$p < $next[$s] ? 'trunk' : 'access','pvid'=>1,
            'tagged'=>$p < $next[$s] ? '10-20,100-150' : '','untagged'=>'1','forbidden'=>'',
            'current_egress'=>$p < $next[$s] ? '1,10-20,100-150' : '1','current_untagged'=>'1'];
        $stp[] = ['kind'=>'port','instance'=>0,'interface_uid'=>$uid($s, $p),'role'=>'designated','role_source'=>'derived',
            'state'=>'forwarding','designated_bridge'=>'8000'.str_replace(':', '', $mac($s))];
    }
    foreach (array_merge([1], range(10, 20), range(100, 150)) as $v) {
        $vlan[] = ['kind'=>'vlan','vlan_id'=>$v,'name'=>"VLAN $v"];
    }
    $gateway->add($id, 'ne.device.snapshot', [$envelope('device', [['chassis_ids'=>[['subtype'=>4,'value'=>$mac($s)]],
        'management_addresses'=>['10.'.intdiv($s, 256).'.'.($s % 256).'.1']]])]);
    $gateway->add($id, 'ne.interfaces.state', [$envelope('interfaces', $rows)]);
    $gateway->add($id, 'ne.port_capability.snapshot', [$envelope('port_capability', $caps)]);
    $gateway->add($id, 'ne.lldp.snapshot', [$envelope('lldp', $lldp[$s] ?? [])]);
    $gateway->add($id, 'ne.vlan.snapshot', [$envelope('vlan', $vlan)]);
    $gateway->add($id, 'ne.stp.snapshot', [$envelope('stp', $stp)]);
    $gateway->add($id, 'ne.lag.snapshot', [$envelope('lag', [])]);
}
$times = [];
for ($r = 0; $r < $runs; ++$r) {
    gc_collect_cycles();
    $start = hrtime(true);
    $network = (new NetworkService($gateway, $now + 5))->build($seed);
    $times[] = (hrtime(true) - $start) / 1e9;
}
sort($times);
$payload = strlen(json_encode($network));
printf("candidates=%d hosts=%d interfaces=%d edges=%d findings=%d payload=%.1fMB\n", $network['budgets']['identity_candidates'] ?? count($network['hosts']), count($network['hosts']), count($network['interfaces']),
    count($network['edges']), count($network['findings']), $payload / 1048576);
printf("build seconds: median=%.2f max=%.2f over %d runs; peak memory=%.0fMB\n", $times[intdiv(count($times), 2)],
    end($times), $runs, memory_get_peak_usage(true) / 1048576);
file_put_contents($argv[2] ?? '/dev/null', json_encode($network));
