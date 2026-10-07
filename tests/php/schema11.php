<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\DatasetReader;
use Modules\NetworkExplorer\Services\EnvelopeValidator;
use Modules\NetworkExplorer\Services\NetworkService;
use Modules\NetworkExplorer\Services\SpeedIntent;
use Modules\NetworkExplorer\Services\VlanService;

/** Schema 1.1: port capability, VLAN and STP datasets, derived expected speed, and unreachable agents. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $rejects = static function (callable $call, string $code, string $message) use ($assert): void {
        try { $call(); $assert(false, $message); }
        catch (InvalidArgumentException $e) { $assert($e->getMessage() === $code, $message.' ('.$e->getMessage().')'); }
    };
    $now = strtotime('2026-10-06T12:00:00Z');
    $envelope = static function (string $dataset, array $data, string $time = '2026-10-06T12:00:00Z',
            string $method = 'native_snmp'): array {
        return ['schema_version'=>'1.1','dataset'=>$dataset,'generation_id'=>'test-g1','attempted_at'=>$time,
            'observed_at'=>$time,'status'=>'ok','complete'=>true,
            'source'=>['method'=>$method,'adapter'=>'test','version'=>'1.1.0'],
            'capability'=>['state'=>'supported','reason'=>null],'errors'=>[],'data'=>$data];
    };
    $validator = new EnvelopeValidator();
    $decode = static fn(array $env) => $validator->decode(json_encode($env), $env['dataset']);

    // Every dataset the native templates produce from both lab fixtures is accepted as-is.
    $runner = __DIR__.'/../js/run_normaliser.cjs';
    $node = trim((string) shell_exec('command -v node'));
    if ($node !== '') {
        $keys = ['ne.raw.system','ne.raw.if.inventory','ne.raw.if.state','ne.raw.if.capability','ne.raw.lldp',
            'ne.raw.vlan','ne.raw.stp','ne.raw.lag'];
        foreach (['sw-core-01','sw-access-17'] as $fixture) {
            foreach ($keys as $key) {
                $json = shell_exec(escapeshellarg($node).' '.escapeshellarg($runner).' '.escapeshellarg($key).' '
                    .escapeshellarg(__DIR__.'/../fixtures/walks/'.$fixture.'.snmprec'));
                $env = json_decode((string) $json, true);
                $assert(is_array($env) && $validator->decode($json, $env['dataset'])['status'] === 'ok',
                    "Native $key output for $fixture validates.");
            }
        }
    }

    $rejects(fn() => $decode(array_replace($envelope('vlan', []), ['schema_version'=>'1.0'])), 'unsupported_schema',
        'A 1.0 envelope cannot carry a 1.1 dataset.');
    $vlanPort = ['kind'=>'port','interface_uid'=>'if-a','mode'=>'trunk','pvid'=>1,'tagged'=>'10,20-22',
        'untagged'=>'1','forbidden'=>'','current_egress'=>'1,10,20-22','current_untagged'=>'1'];
    $assert(count($decode($envelope('vlan', [['kind'=>'vlan','vlan_id'=>10,'name'=>'Users'], $vlanPort]))['data']) === 2,
        'VLAN and port rows validate.');
    $rejects(fn() => $decode($envelope('vlan', [array_replace($vlanPort, ['tagged'=>'10;20'])])), 'invalid_vlan',
        'Malformed VLAN range strings are rejected.');
    $rejects(fn() => $decode($envelope('vlan', [['kind'=>'vlan','vlan_id'=>4095,'name'=>null]])), 'invalid_vlan',
        'Reserved VLAN IDs are rejected.');
    $rejects(fn() => $decode($envelope('stp', [['kind'=>'bridge','instance'=>0,'bridge_id'=>'<b>',
        'root_bridge_id'=>'8000001122334401']])), 'invalid_stp', 'Bridge IDs are bounded hex.');
    $rejects(fn() => $decode($envelope('port_capability', [['uid'=>'if-a','supported_speeds_bps'=>['1G']]])),
        'invalid_port_capability', 'Speed lists are positive integers.');
    $rejects(fn() => $decode($envelope('lldp', [['local_interface_uid'=>'if-a','local_port_id'=>['subtype'=>5,'value'=>'Gi1'],
        'remote_chassis_id'=>['subtype'=>4,'value'=>'00:11'],'remote_port_id'=>['subtype'=>5,'value'=>'Gi2'],
        'remote_management_addresses'=>[],'remote_pvid'=>0]])), 'invalid_lldp_peer', 'LLDP peer VLAN is bounded.');

    // Range strings round-trip.
    $assert(VlanService::compress(VlanService::expand('20-22,1,10,21')) === '1,10,20-22', 'VLAN ranges normalise.');

    // Per-port override macros: quoted and unquoted context, plain bit/s only.
    $overrides = SpeedIntent::overrides([
        ['macro'=>'{$NE.IF.EXPECTED_SPEED:"Gi1/0/23"}','value'=>'1000000000'],
        ['macro'=>'{$NE.IF.EXPECTED_SPEED:Te1/0/1}','value'=>'10000000000'],
        ['macro'=>'{$NE.IF.EXPECTED_SPEED:"Gi1/0/2"}','value'=>'1G'],
        ['macro'=>'{$NE.IF.EXPECTED_SPEED:"Gi1/0/3"}','value'=>'0']]);
    $assert($overrides === ['Gi1/0/23'=>1000000000, 'Te1/0/1'=>10000000000], 'Only plain numeric overrides apply.');

    $gig = ['advertised_speeds_bps'=>[10000000,100000000,1000000000]];
    $derive = static fn(array $if, ?array $cap, ?array $lldp = null, array $o = []) => SpeedIntent::derive($if, $cap, $lldp, $o);
    $assert($derive(['name'=>'Gi1','expected_speed_bps'=>100000000], $gig) === [100000000,'policy','dataset'],
        'Dataset policy wins.');
    $assert($derive(['name'=>'Gi1/0/23'], $gig, null, $overrides) === [1000000000,'policy','port_macro'],
        'The per-port macro is policy.');
    $assert($derive(['name'=>'Gi1'], $gig + ['partner_advertised_speeds_bps'=>[10000000,100000000]])
        === [100000000,'negotiable','partner_mau'], 'Negotiable speed is the best speed both ends advertise.');
    $assert($derive(['name'=>'Gi1'], $gig, ['remote_advertised_speeds_bps'=>[1000000000]])
        === [1000000000,'negotiable','lldp_peer'], 'LLDP 802.3 supplies the partner list when MAU has none.');
    $assert($derive(['name'=>'Te1'], ['supported_speeds_bps'=>[10000000000],'advertised_speeds_bps'=>[]],
        ['remote_advertised_speeds_bps'=>[],'capabilities'=>['enabled'=>['bridge']]])
        === [10000000000,'uplink_capability','lldp_bridge_peer'], 'An uplink to a bridge expects the port\'s best speed.');
    $assert($derive(['name'=>'Gi1'], $gig, ['capabilities'=>['enabled'=>['telephone']]]) === [null,'unknown',null],
        'An edge device without a partner list sets no expectation.');

    // Two switches in one domain, linked Gi1 <-> Gi1 and seen over LLDP from both ends.
    $gateway = new FixtureGateway();
    $host = static fn(string $id, int $available) => ['hostid'=>$id,'host'=>'sw-'.$id,'name'=>'Switch '.$id,
        'tags'=>[['tag'=>'ne.domain','value'=>'d-a']],
        'interfaces'=>[['type'=>2,'useip'=>1,'ip'=>'192.0.2.'.$id,'available'=>$available]], 'macros'=>[]];
    $gateway->hostRows = [$host('1', 1), $host('2', 1), $host('3', 2), $host('4', 1)];
    $port = static fn(string $uid, string $name, int $speed, string $duplex = 'full') => ['uid'=>$uid,'if_index'=>1,
        'name'=>$name,'physical'=>true,'admin_status'=>'up','oper_status'=>'up','speed_bps'=>$speed,'duplex'=>$duplex];
    $lldp = static fn(string $local, string $remote, array $extra = []) => ['local_interface_uid'=>$local,
        'local_port_id'=>['subtype'=>5,'value'=>'Gi1'],'remote_chassis_id'=>['subtype'=>7,'value'=>'chassis-'.$remote],
        'remote_port_id'=>['subtype'=>5,'value'=>'Gi1'],'remote_management_addresses'=>[],'remote_system_name'=>null] + $extra;
    $stpBridge = static fn(string $id, string $root, int $since = 86400) => ['kind'=>'bridge','instance'=>0,'protocol'=>'rstp',
        'bridge_id'=>$id,'root_bridge_id'=>$root,'root_cost'=>0,'root_port_uid'=>null,'priority'=>32768,'vlans'=>null,
        'topology_changes'=>3,'time_since_topology_change_s'=>$since];
    $stpPort = static fn(string $uid, string $role, string $state) => ['kind'=>'port','instance'=>0,'interface_uid'=>$uid,
        'role'=>$role,'role_source'=>'derived','state'=>$state,'designated_bridge'=>'8000000000000001'];
    foreach (['1','2','3'] as $id) {
        $gateway->add($id,'ne.device.snapshot',[$envelope('device',[['chassis_ids'=>[['subtype'=>7,'value'=>'chassis-'.$id]],
            'management_addresses'=>['192.0.2.'.$id]]])]);
    }
    $gateway->add('1','ne.interfaces.state',[$envelope('interfaces',[$port('if-a1','Gi1',100000000),$port('if-a2','Gi2',1000000000,'half')])]);
    $gateway->add('2','ne.interfaces.state',[$envelope('interfaces',[$port('if-b1','Gi1',100000000)])]);
    $gateway->add('3','ne.interfaces.state',[$envelope('interfaces',[$port('if-c1','Gi1',1000000000)])]);
    $gateway->add('1','ne.port_capability.snapshot',[$envelope('port_capability',[['uid'=>'if-a1']
        + $gig + ['partner_advertised_speeds_bps'=>[10000000,100000000,1000000000]]])]);
    $gateway->add('1','ne.lldp.snapshot',[$envelope('lldp',[$lldp('if-a1','2',['remote_pvid'=>99]),
        $lldp('if-a2','9',['remote_duplex'=>'full','remote_pvid'=>5])])]);
    $gateway->add('2','ne.lldp.snapshot',[$envelope('lldp',[$lldp('if-b1','1')])]);
    $gateway->add('1','ne.vlan.snapshot',[$envelope('vlan',[['kind'=>'vlan','vlan_id'=>10,'name'=>'Users'],
        array_replace($vlanPort, ['interface_uid'=>'if-a1']),
        ['kind'=>'port','interface_uid'=>'if-a2','mode'=>'access','pvid'=>10,'untagged'=>'10','current_egress'=>'10']])]);
    $gateway->add('2','ne.vlan.snapshot',[$envelope('vlan',[['kind'=>'port','interface_uid'=>'if-b1','mode'=>'trunk',
        'pvid'=>99,'tagged'=>'10','untagged'=>'99','current_egress'=>'10,99','current_untagged'=>'99']])]);
    $gateway->add('1','ne.stp.snapshot',[$envelope('stp',[$stpBridge('8000000000000001','8000000000000001'),
        $stpPort('if-a1','designated','forwarding')])]);
    $gateway->add('2','ne.stp.snapshot',[$envelope('stp',[$stpBridge('8000000000000002','8000000000000001', 600),
        $stpPort('if-b1','root','forwarding')])]);
    $gateway->add('3','ne.stp.snapshot',[$envelope('stp',[$stpBridge('8000000000000003','1000000000000003')])]);
    $gateway->add('3','ne.interfaces.inventory.attempt',[$envelope('interfaces',[],'2026-10-06T12:00:30Z')]);

    $network = (new NetworkService($gateway,$now))->build();
    $assert($network['schema_version'] === '1.1' && !isset($network['unsupported']), 'VLAN and STP are no longer unsupported.');
    $hosts = array_column($network['hosts'],null,'hostid');
    $ports = array_column($network['interfaces'],null,'uid');
    $rules = array_count_values(array_column($network['findings'],'rule'));

    $a1 = $ports['if-a1'];
    $assert($a1['expected_speed_bps'] == 1000000000 && $a1['expected_speed_source'] === 'negotiable'
        && $a1['expected_speed_basis'] === 'partner_mau' && $a1['state'] === 'speed_observation',
        'A 1G-capable pair running at 100M is flagged with source "negotiable".');
    $assert(str_contains($a1['reason'], 'both ends advertise'), 'The reason names the expectation source.');
    $assert($ports['if-b1']['expected_speed_source'] === 'unknown' && $ports['if-b1']['state'] === 'normal',
        'Without capability evidence no speed expectation is invented.');
    $assert($ports['if-a2']['duplex_mismatch'] && ($rules['duplex_mismatch'] ?? 0) === 1,
        'Half duplex against a full-duplex LLDP peer is a mismatch.');

    $assert($hosts['1']['vlans'] === [['vlan_id'=>10,'name'=>'Users']] && $hosts['3']['vlans'] === null,
        'Hosts list their VLANs; null means no VLAN data.');
    $assert($a1['vlan']['carried'] === '1,10,20-22' && $a1['vlan']['tagged'] === '10,20-22' && $a1['vlan']['untagged'] === '1',
        'Port VLAN view separates tagged and untagged.');
    $edge = current(array_filter($network['edges'], static fn($e) => in_array('if-a1', [$e['source_uid'],$e['target_uid']], true)));
    $assert($edge['vlan']['common'] === '10', 'Link carries only VLANs common to both ends.');
    $assert(($rules['native_vlan_mismatch'] ?? 0) === 2, 'Native VLAN mismatch on the link, and against an LLDP-only peer.');
    $assert(($rules['vlan_not_carried'] ?? 0) === 1, 'One-sided VLANs are reported once per link.');

    $assert($hosts['1']['stp'][0]['is_root'] && !$hosts['2']['stp'][0]['is_root'], 'Root bridge is marked.');
    $assert($edge['stp']['source']['state'] === 'forwarding' && !$edge['stp']['blocked'], 'Links carry STP state of both ends.');
    $assert(($rules['stp_root_disagreement'] ?? 0) === 1, 'A switch that sees a different root is flagged.');
    $assert(($rules['stp_topology_change'] ?? 0) === 1, 'A recent topology change is reported.');

    $assert(($rules['snmp_unreachable'] ?? 0) === 1 && !isset($rules['collection_interfaces']),
        'An unreachable agent is one finding, not one per dataset.');
    $assert(!isset($hosts['4']), 'A host without Network Explorer items is not part of the network view.');
    $assert($hosts['3']['snmp_available'] === false && $hosts['1']['snmp_available'] === true, 'SNMP availability is exposed.');
    $q = array_column(array_filter($network['quality'], static fn($r) => $r['hostid'] === '3'),null,'dataset');
    $assert($q['interfaces']['status'] === 'failed' && in_array('agent_unreachable',$q['interfaces']['errors'],true),
        'An unreachable SNMP agent fails native datasets even though Zabbix recorded no failed attempt.');
    $assert($q['interfaces']['attempted_at'] === '2026-10-06T12:00:30Z', 'The inventory attempt counts as an interfaces attempt.');
    $assert(!isset($q['vlan']) && isset($q['stp']), 'Optional datasets are reported only where the host collects them.');
    $assert(!str_contains(json_encode($network), 'macros'), 'Host macros never reach the browser.');

    // Native state walks carry inventory attributes as null; the inventory values survive the merge.
    $split = new FixtureGateway();
    $split->add('1','ne.interfaces.inventory',[$envelope('interfaces',[array_replace($port('if-x','Gi1',1000000000),
        ['alias'=>'Uplink','type'=>6,'mtu'=>1500])])]);
    $split->add('1','ne.interfaces.state',[$envelope('interfaces',[array_replace($port('if-x','Gi1',100000000),
        ['alias'=>null,'type'=>null,'physical'=>null,'mtu'=>null])])]);
    $row = (new DatasetReader($split,$now))->read(['1'=>['hostid'=>'1']])['datasets']['1']['interfaces']['data'][0];
    $assert($row['physical'] === true && $row['alias'] === 'Uplink' && $row['mtu'] === 1500 && $row['speed_bps'] === 100000000,
        'State rows refresh operational fields without erasing inventory attributes.');

    $bridge = ['kind'=>'bridge','instance'=>0,'protocol'=>'rstp','bridge_id'=>str_repeat('a',16),
        'root_bridge_id'=>str_repeat('a',16),'root_cost'=>0,'root_port_uid'=>null];
    $assert(count($decode($envelope('stp', [$bridge]))['data']) === 1, 'A well-formed STP bridge row is accepted.');
    $rejects(fn() => $decode($envelope('stp', [array_replace($bridge, ['topology_changes'=>[1]])])), 'invalid_stp',
        'STP counters must be integers.');
    $rejects(fn() => $decode($envelope('stp', [array_replace($bridge, ['protocol'=>'spanning'])])), 'invalid_stp',
        'STP protocol is one of the schema values.');

    // A VLAN row whose interface is unresolved must never attach to an LLDP edge with an unmapped local port.
    $orphan = VlanService::port(['kind'=>'port','interface_uid'=>null,'mode'=>'trunk','pvid'=>99,'tagged'=>'99',
        'untagged'=>null,'forbidden'=>null,'current_egress'=>null,'current_untagged'=>null]);
    $edges = [['id'=>'e1','source'=>'1','source_uid'=>null,'target'=>'2','target_uid'=>'if-b1']];
    $found = VlanService::link($edges, ['1'=>[''=>$orphan], '2'=>['if-b1'=>$orphan]], []);
    $assert($found === [] && !isset($edges[0]['vlan']), 'An edge end without a local port carries no VLAN comparison.');

    echo "Schema 1.1, VLAN, STP and expected-speed checks passed ($checks checks).\n";
})();
