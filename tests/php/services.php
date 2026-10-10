<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\DataGateway;
use Modules\NetworkExplorer\Services\DatasetReader;
use Modules\NetworkExplorer\Services\EnvelopeValidator;
use Modules\NetworkExplorer\Services\NetworkService;
use Modules\NetworkExplorer\Services\Navigation;
use Modules\NetworkExplorer\Services\PortPolicy;
use Modules\NetworkExplorer\Services\ReportService;

final class FixtureGateway implements DataGateway {
    public array $hostRows = [];
    public array $itemRows = [];
    public array $values = [];
    public array $requestedHistory = [];
    public array $hostQueries = [];
    public function hosts(array $hostids = [], array $tags = []): array {
        $this->hostQueries[] = ['hostids'=>$hostids, 'tags'=>$tags];
        $byName = [];
        foreach ($tags as $tag) {
            $byName[$tag['tag']][] = $tag['value'];
        }
        // Like the API: sorted by host ID, at most one row more than the candidate budget.
        $rows = $this->hostRows;
        usort($rows, static fn($a, $b) => (int) $a['hostid'] <=> (int) $b['hostid']);
        return array_slice(array_values(array_filter($rows, static function ($host) use ($hostids, $byName): bool {
            if ($hostids && !in_array((string) $host['hostid'], $hostids, true)) {
                return false;
            }
            foreach ($byName as $name => $values) {
                if (!array_filter($host['tags'] ?? [], static fn($t) => $t['tag'] === $name
                        && in_array($t['value'], $values, true))) {
                    return false;
                }
            }
            return true;
        })), 0, \Modules\NetworkExplorer\Services\Limits::CANDIDATE_HOSTS + 1);
    }
    public function tagged(array $names): array {
        return array_values(array_filter(array_map(static fn($host) => ['hostid'=>$host['hostid'],
            'tags'=>array_values(array_filter($host['tags'] ?? [], static fn($t) => in_array($t['tag'], $names, true)))],
            $this->hostRows), static fn($row) => $row['tags'] !== []));
    }
    public array $itemQueries = [];
    public function networkHostids(array $keys, int $limit): array {
        $rows = array_slice(array_values(array_filter($this->itemRows, static fn($item) =>
            in_array($item['key_'], $keys, true))), 0, $limit);
        $ids = array_values(array_unique(array_map(static fn($item) => (string) $item['hostid'], $rows)));
        usort($ids, static fn($a, $b) => strnatcmp($a, $b));
        return $ids;
    }
    public function items(array $hostids, array $keys = []): array {
        $this->itemQueries[] = ['hostids'=>$hostids, 'keys'=>$keys];
        return array_values(array_filter($this->itemRows, static fn($item) =>
            in_array((string) $item['hostid'], $hostids, true) && (!$keys || in_array($item['key_'], $keys, true))));
    }
    public function history(array $items, int $limit): array {
        $this->requestedHistory = $items;
        $values = [];
        foreach ($items as $item) {
            $values[(string) $item['itemid']] = array_slice($this->values[$item['itemid']] ?? [], 0, $limit);
        }
        return $values;
    }
    public function add(string $hostid, string $key, array $envelopes, int $type = 4, int $state = 0): void {
        $id = (string) (count($this->itemRows) + 1000);
        $this->itemRows[] = ['itemid'=>$id, 'hostid'=>$hostid, 'key_'=>$key, 'value_type'=>$type,
            'state'=>$state,'status'=>0];
        $this->values[$id] = array_map(static fn($envelope) => ['value'=>is_array($envelope)
            ? json_encode($envelope, JSON_THROW_ON_ERROR) : $envelope], $envelopes);
    }
}

(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = strtotime('2026-10-06T12:00:00Z');
    $envelope = static function (string $dataset, array $data, string $time = '2026-10-06T12:00:00Z',
            string $status = 'ok'): array {
        return ['schema_version'=>'1.0','dataset'=>$dataset,'generation_id'=>'test-g1',
            'attempted_at'=>$time,'observed_at'=>in_array($status, ['failed','unsupported'], true) ? null : $time,
            'status'=>$status,'complete'=>$status === 'ok', 'source'=>['method'=>'fixture','adapter'=>'test','version'=>'1.0'],
            'capability'=>['state'=>$status === 'partial' ? 'partial'
                : ($status === 'unsupported' ? 'unsupported' : 'supported'),'reason'=>null],
            'errors'=>[], 'data'=>$data];
    };
    $host = static fn(string $id, string $domain): array => ['hostid'=>$id,'host'=>'test-switch-'.$id,
        'name'=>'Test switch '.$id,'tags'=>$domain === '' ? [] : [['tag'=>'ne.domain','value'=>$domain]],
        'interfaces'=>[['type'=>2,'useip'=>1,'ip'=>'192.0.2.'.(int) $id]]];
    $port = static fn(string $uid, int $index): array => ['uid'=>$uid,'if_index'=>$index,
        'name'=>'Gi'.$index,'physical'=>true,'admin_status'=>'up','oper_status'=>'up',
        'speed_bps'=>1000000000,'duplex'=>'full'];
    $policy = new PortPolicy();
    $assert($policy->evaluate($port('a',1),'current')['state'] === 'normal', 'Known up state is normal.');
    $assert(!$policy->evaluate($port('a',1),'current')['speed_degraded'], 'Unknown intent never degrades.');
    $slow = array_replace($port('a',1), ['speed_bps'=>100000000,'expected_speed_bps'=>1000000000]);
    $assert($policy->evaluate($slow,'current')['state'] === 'speed_observation', 'Persistence must not be invented.');
    $slow['speed_degradation_persistent'] = true;
    $assert($policy->evaluate($slow,'current')['state'] === 'speed_observation'
        && !$policy->evaluate($slow,'current')['speed_warning_confirmed'],
        'Undeclared producer flags cannot invent sustained speed degradation.');
    $assert($policy->evaluate($slow,'stale')['state'] === 'unknown', 'Stale evidence cannot be green or degraded.');
    $assert($policy->evaluate(array_replace($slow,['admin_status'=>'down']),'stale')['state'] === 'disabled', 'Admin disable distinct from stale.');
    $assert($policy->evaluate(array_replace($port('a',1),['duplex'=>'half']),'current')['state'] === 'duplex_observation',
        'Half duplex is an observation, not a proven mismatch.');

    $validator = new EnvelopeValidator();
    $assert($validator->decode(json_encode($envelope('interfaces',[$port('a',1)])), 'interfaces')['data'][0]['uid'] === 'a',
        'Valid canonical envelope accepted.');
    foreach ([['{bad','invalid_json'], [json_encode(array_replace($envelope('device',[]),['schema_version'=>'2.0'])),'unsupported_schema'],
            [json_encode($envelope('interfaces',[$port('a',1),$port('a',2)])),'duplicate_interface_identity']] as [$value,$expected]) {
        try { $validator->decode($value, $expected === 'duplicate_interface_identity' ? 'interfaces' : 'device');
            throw new RuntimeException('Expected rejection: '.$expected); }
        catch (InvalidArgumentException $error) { $assert($error->getMessage() === $expected, 'Validation reason: '.$expected); }
    }
    $redacted = ['local_interface_uid'=>'a','local_port_id'=>['subtype'=>5,'value'=>'Gi1'],
        'remote_chassis_id'=>['subtype'=>null,'value'=>''],'remote_port_id'=>['subtype'=>null,'value'=>'']];
    $assert(count($validator->decode(json_encode($envelope('lldp',[$redacted])), 'lldp')['data']) === 1,
        'Redacted remote identity is valid and stays unresolved.');

    $malformedOutcomes = [
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','failed'),['complete'=>true]),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','failed'),['data'=>[$port('forged',1)]]),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','failed'),['observed_at'=>'2026-10-06T12:00:00Z']),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','unsupported'),['complete'=>true]),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','unsupported'),['data'=>[$port('forged',1)]]),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','unsupported'),['observed_at'=>'2026-10-06T12:00:00Z']),
        array_replace($envelope('interfaces',[],'2026-10-06T12:00:00Z','unsupported'),['capability'=>['state'=>'supported']]),
        array_replace($envelope('interfaces',[$port('forged',1)],'2026-10-06T12:00:00Z','partial'),['complete'=>true]),
        array_replace($envelope('interfaces',[$port('forged',1)],'2026-10-06T12:00:00Z','partial'),['observed_at'=>null]),
        array_replace($envelope('interfaces',[$port('forged',1)],'2026-10-06T12:00:00Z','partial'),['capability'=>['state'=>'supported']]),
        array_replace($envelope('interfaces',[$port('forged',1)]),['errors'=>[['code'=>'collection_failed']]]),
        array_replace($envelope('interfaces',[$port('forged',1)]),['capability'=>['state'=>'partial']])
    ];
    foreach ($malformedOutcomes as $malformed) {
        try { $validator->decode(json_encode($malformed),'interfaces'); throw new RuntimeException('Malformed outcome accepted'); }
        catch (InvalidArgumentException $e) { $assert(true,'Schema outcome invariant rejected.'); }
        $malformedGateway = new FixtureGateway();
        $malformedGateway->hostRows = [$host('1','d-a')];
        $malformedGateway->add('1','ne.interfaces.state',[$malformed]);
        $invalidNetwork = (new NetworkService($malformedGateway,$now))->build(['1']);
        $invalidQuality = array_column($invalidNetwork['quality'],null,'dataset')['interfaces'];
        $assert($invalidNetwork['interfaces'] === [] && $invalidQuality['freshness'] === 'unknown'
            && $invalidQuality['status'] === 'failed', 'Malformed outcome never creates fresh ports.');
    }
    $validPartial = $validator->decode(json_encode($envelope('interfaces',[$port('partial',1)],
        '2026-10-06T12:00:00Z','partial')), 'interfaces');
    $assert($validPartial['status'] === 'partial' && !$validPartial['complete'], 'Valid partial observed rows remain usable.');

    $aliased = array_replace($port('alias-port',1),['alias'=>'Uplink to rack']);
    $assert($validator->decode(json_encode($envelope('interfaces',[$aliased])), 'interfaces')['data'][0]['alias']
        === 'Uplink to rack', 'Optional canonical alias is typed and accepted.');
    $aliased['alias'] = null;
    $assert($validator->decode(json_encode($envelope('interfaces',[$aliased])), 'interfaces')['data'][0]['alias'] === null,
        'Nullable alias is accepted.');
    $aliased['alias'] = [];
    try { $validator->decode(json_encode($envelope('interfaces',[$aliased])), 'interfaces'); throw new RuntimeException('Alias array accepted'); }
    catch (InvalidArgumentException $e) { $assert($e->getMessage() === 'invalid_field_type','Alias array is rejected.'); }

    $gateway = new FixtureGateway();
    $gateway->hostRows = [$host('1','d-a')];
    $gateway->add('1','ne.interfaces.inventory',[$envelope('interfaces',[$port('a',1),$port('retired',2)])]);
    $gateway->add('1','ne.interfaces.state',[$envelope('interfaces',[array_replace($port('a',11),['alias'=>'Uplink'])])]);
    $gateway->add('1','ne.interfaces.attempt',[$envelope('interfaces',[],'2026-10-06T11:58:00Z','failed')]);
    $network = (new NetworkService($gateway,$now))->build(['1']);
    $byUid = array_column($network['interfaces'],null,'uid');
    $assert($network['findings'] !== [] && array_filter($network['findings'], static fn($f) =>
            array_keys($f) !== ['id','hostid','interface_uid','edge_id','severity','rule','title','reason']
            || !preg_match('/^[0-9a-f]{64}$/D', $f['id'])) === []
        && count(array_unique(array_column($network['findings'], 'id'))) === count($network['findings']),
        'Every finding has one shape and a unique stable ID.');
    $assert($byUid['a']['if_index'] === 11 && $byUid['a']['state'] === 'normal', 'Stable UID carries current renumbered locator.');
    $assert($byUid['a']['alias'] === 'Uplink', 'Permitted interface alias is retained in widget and report payloads.');
    $assert($byUid['retired']['state'] === 'unknown' && $byUid['retired']['freshness'] === 'unknown',
        'An absent state row must not become a fresh green inventory ghost.');
    $q = array_column($network['quality'],null,'dataset')['interfaces'];
    $assert($q['status'] === 'ok' && !$q['retained'], 'Old failed attempt cannot override newer complete success.');

    $unsupportedAttempt = new FixtureGateway();
    $unsupportedAttempt->add('1','ne.interfaces.state',[$envelope('interfaces',[$port('a',1)])]);
    $unsupportedAttempt->add('1','ne.interfaces.attempt',[$envelope('interfaces',[],'2026-10-06T11:59:00Z')],4,1);
    $q = array_column((new DatasetReader($unsupportedAttempt,$now))->read(['1'=>[]])['quality'],null,'dataset')['interfaces'];
    $assert($q['status'] === 'failed' && in_array('item_not_supported',$q['errors'],true),
        'Unsupported attempt master cannot report old successful history as current collection success.');

    $disabledAttempt = new FixtureGateway();
    $disabledAttempt->add('1','ne.interfaces.state',[$envelope('interfaces',[$port('a',1)])]);
    $disabledAttempt->add('1','ne.interfaces.attempt',[$envelope('interfaces',[])],4);
    $disabledAttempt->itemRows[1]['status'] = 1;
    $q = array_column((new DatasetReader($disabledAttempt,$now))->read(['1'=>[]])['quality'],null,'dataset')['interfaces'];
    $assert($q['status'] === 'failed' && in_array('item_disabled',$q['errors'],true),
        'Disabled attempt master is diagnosed independently from retained snapshot freshness.');

    $gateway->add('1','ne.lldp.snapshot',[$envelope('lldp',[$redacted],'2026-10-06T11:00:00Z')]);
    $gateway->add('1','ne.lldp.attempt',[$envelope('lldp',[],'2026-10-06T12:00:00Z','failed')]);
    $read = (new DatasetReader($gateway,$now))->read(['1'=>['hostid'=>'1']]);
    $q = array_column($read['quality'],null,'dataset')['lldp'];
    $assert($q['status'] === 'failed' && $q['freshness'] === 'stale' && $q['retained'],
        'Failed collection keeps independently stale last success.');
    $assert($q['observed_at'] === '2026-10-06T11:00:00Z' && $q['attempted_at'] === '2026-10-06T12:00:00Z',
        'Attempt time cannot refresh observed time.');
    $assert(count($read['datasets']['1']['lldp']['data']) === 1, 'Failure does not erase retained observations.');

    $bad = new FixtureGateway();
    $bad->add('1','ne.device.snapshot',['{bad',$envelope('device',[],'2026-10-06T11:00:00Z')]);
    $read = (new DatasetReader($bad,$now))->read(['1'=>['hostid'=>'1']]);
    $q = array_column($read['quality'],null,'dataset')['device'];
    $assert($q['status'] === 'failed' && in_array('invalid_json',$q['errors'],true), 'Malformed latest envelope shows failure with retained valid row.');
    $bad = new FixtureGateway();
    $bad->add('1','ne.device.snapshot',[$envelope('device',[],'2026-10-06T12:10:00Z')]);
    $q = array_column((new DatasetReader($bad,$now))->read(['1'=>[]])['quality'],null,'dataset')['device'];
    $assert($q['freshness'] === 'unknown' && in_array('clock_skew',$q['errors'],true), 'Future observations never claim current.');
    $bad = new FixtureGateway();
    $bad->add('1','ne.device.snapshot',[$envelope('device',[])],3);
    $assert((new DatasetReader($bad,$now))->read(['1'=>[]])['datasets'] === [], 'Incorrect history type is not guessed.');

    $isolated = new FixtureGateway();
    $isolated->hostRows = [$host('1','d-a'),$host('2','d-a'),$host('3','d-a'),$host('4','d-b')];
    foreach (['1','2','3','4'] as $id) {
        $isolated->add($id,'ne.device.snapshot',[$envelope('device',[['chassis_ids'=>[['subtype'=>7,'value'=>'chassis-'.$id]],
            'management_addresses'=>['192.0.2.'.(int)$id]]])]);
        $isolated->add($id,'ne.interfaces.state',[$envelope('interfaces',[$port('if-'.$id,1)])]);
    }
    $lldp = static fn(string $local, string $remote): array => ['local_interface_uid'=>'if-'.$local,
        'local_port_id'=>['subtype'=>5,'value'=>'Gi1'],'remote_chassis_id'=>['subtype'=>7,'value'=>'chassis-'.$remote],
        'remote_port_id'=>['subtype'=>5,'value'=>'Gi1'],'remote_management_addresses'=>[],'remote_system_name'=>null];
    $isolated->add('1','ne.lldp.snapshot',[$envelope('lldp',[$lldp('1','2'),$lldp('1','4')])]);
    $isolated->add('2','ne.lldp.snapshot',[$envelope('lldp',[$lldp('2','3')])]);
    $network = (new NetworkService($isolated,$now))->build(['1'],'192.0.2.0/24');
    $assert(array_column($network['hosts'],'hostid') === ['1','2'], 'Seed expansion is one hop, not whole domain.');
    $assert(count($network['edges']) === 2, 'One-hop graph retains source unresolved peer, drops second-hop link.');
    $assert(!str_contains(json_encode($network),'chassis-4'), 'Cross-domain remote identifiers absent from payload.');
    $assert((new NetworkService($isolated,$now))->build(['999'])['hosts'] === [], 'Inaccessible seed must not broaden to all visible hosts.');
    try { (new NetworkService($isolated,$now))->build(['1'],'192.0.2.0/999'); throw new RuntimeException('CIDR accepted'); }
    catch (InvalidArgumentException $e) { $assert($e->getMessage() === 'invalid_management_cidr','Invalid CIDR is explicit.'); }

    $url = Navigation::dashboard('123','if-a');
    $assert(str_contains($url,'action=host.dashboard.view') && !str_contains($url,'dashboardid'), 'Destination host chooses its own dashboard.');
    $fragment = json_decode(rawurldecode(explode('#ne=',$url)[1]),true);
    $assert($fragment === ['hostid'=>'123','uid'=>'if-a'], 'Interface fragment matches widget protocol.');
    try { Navigation::dashboard('123','<script>'); throw new RuntimeException('UID accepted'); }
    catch (InvalidArgumentException $e) { $assert(true,'Unsafe interface navigation rejected.'); }
    $reports = new ReportService();
    $csv = $reports->csv([['name'=>' =HYPERLINK("https://example.test")','detail'=>"line1\nline2",'negative'=>'-1']]);
    $assert(str_contains($csv,"' =HYPERLINK") && str_contains($csv,"'-1"), 'CSV formula and whitespace injection defended.');
    $assert(str_contains($reports->csv([['name'=>"=1+1\xff"]]), "'=1+1"), 'CSV formulas are escaped even in invalid UTF-8.');
    $stream = fopen('php://temp','w+'); fwrite($stream,$csv); rewind($stream); fgetcsv($stream,0,',','"','');
    $row = fgetcsv($stream,0,',','"',''); fclose($stream);
    $assert($row[1] === "line1\nline2", 'CSV preserves multiline data correctly.');
    $assert(count($reports->rows($network,'inventory')) === 2, 'Reports share scoped visible host inventory.');
    $contextual = $reports->contextualRows($network,'inventory');
    $assert($contextual[0]['report_scope']['neighbour_hops'] === 1
        && $contextual[0]['report_generated_at'] === $network['generated_at']
        && count($contextual[0]['observation_coverage']) === 4,
        'CSV contextual rows carry scope, generation time and all dataset coverage.');
    echo "Dataset, policy, report and navigation checks passed ($checks checks).\n";
})();
