<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\DataGateway;
use Modules\NetworkExplorer\Services\DatasetReader;
use Modules\NetworkExplorer\Services\EnvelopeValidator;
use Modules\NetworkExplorer\Services\StoredEnvelope;

/** A gateway whose items carry Zabbix's lastclock and whose history rows carry their clock, as the API returns them. */
final class StoredGateway implements DataGateway {
    public array $itemRows = [];
    public array $values = [];
    public function hosts(array $hostids = [], array $tags = []): array { return []; }
    public function hostids(array $tags, int $limit): array { return []; }
    public function networkHostids(array $keys, int $limit, ?array $hostids = null): array { return []; }
    public function tagged(array $names): array { return []; }
    public function items(array $hostids, array $keys = []): array {
        return array_values(array_filter($this->itemRows, static fn($item) =>
            in_array((string) $item['hostid'], $hostids, true) && (!$keys || in_array($item['key_'], $keys, true))));
    }
    public function history(array $items, int $limit): array {
        $values = [];
        foreach ($items as $item) {
            $values[(string) $item['itemid']] = array_slice($this->values[$item['itemid']] ?? [], 0, $limit);
        }
        return $values;
    }
    /** @param array $rows [[clock, envelope], ...], newest first */
    public function add(string $hostid, string $key, array $rows, int $type = 4, int $lastclock = 0): void {
        $id = (string) (count($this->itemRows) + 5000);
        $this->itemRows[] = ['itemid'=>$id, 'hostid'=>$hostid, 'key_'=>$key, 'value_type'=>$type, 'state'=>0,
            'status'=>0, 'lastclock'=>(string) $lastclock];
        $this->values[$id] = array_map(static fn($row) => ['clock'=>(string) $row[0],
            'value'=>json_encode($row[1], JSON_THROW_ON_ERROR)], $rows);
    }
}

/** Stored native envelopes carry no timestamps; the reader takes them from Zabbix and restores the canonical form. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };
    $now = strtotime('2026-11-24T12:00:00Z');
    // A stored envelope as the native templates write it: no attempted_at, observed_at or generation_id.
    $stored = static fn(string $dataset, array $data, string $status = 'ok') => ['schema_version'=>'1.1',
        'dataset'=>$dataset, 'status'=>$status, 'complete'=>$status === 'ok',
        'source'=>['method'=>'native_snmp', 'adapter'=>'test', 'version'=>'2.3.0'],
        'capability'=>['state'=>$status === 'ok' ? 'supported' : ($status === 'partial' ? 'partial' : 'unsupported'),
            'reason'=>null], 'errors'=>$status === 'ok' ? [] : [['code'=>$status === 'failed' ? 'collection_failed'
            : 'unsupported', 'message'=>'x']], 'warnings'=>[], 'data'=>$data, 'timing'=>'zabbix'];
    $validator = new EnvelopeValidator();
    $decode = static fn(array $envelope, string $dataset, int $clock, ?int $observed = null) => $validator->decode(
        StoredEnvelope::rehydrate(json_encode($envelope, JSON_THROW_ON_ERROR), $clock, $observed), $dataset);

    // A canonical envelope (collector, lab, an earlier template) is left exactly as it is.
    $canonical = '{"schema_version":"1.1","dataset":"lldp","observed_at":"2026-11-24T11:00:00Z"}';
    $assert(StoredEnvelope::rehydrate($canonical, $now) === $canonical, 'A canonical envelope is not touched.');

    // The newest snapshot was stored at 11:00 and confirmed by every complete observation since, the last at 11:58.
    $device = $decode($stored('device', [['chassis_ids'=>[['subtype'=>7, 'value'=>'chassis-1']],
        'management_addresses'=>['192.0.2.1'], 'boot_at'=>'2026-11-20T12:00:00Z']]), 'device',
        $now - 3600, $now - 120);
    $assert($device['observed_at'] === '2026-11-24T11:58:00Z' && $device['attempted_at'] === '2026-11-24T11:58:00Z',
        'A confirmed snapshot is observed at the last complete observation, not when it was stored.');
    $assert($device['data'][0]['uptime_s'] === 4 * 86400 - 120 && !array_key_exists('boot_at', $device['data'][0]),
        'Uptime is restored from the boot time, at the observation time.');
    $assert(preg_match('/^device-zabbix-\d+$/D', $device['generation_id']) === 1, 'A generation ID is supplied.');
    $older = $decode($stored('device', [['chassis_ids'=>[['subtype'=>7, 'value'=>'chassis-1']],
        'management_addresses'=>[], 'boot_at'=>null]]), 'device', $now - 7200);
    $assert($older['observed_at'] === '2026-11-24T10:00:00Z' && $older['data'][0]['uptime_s'] === null,
        'An older row is observed at its own clock; an unknown boot time is an unknown uptime.');

    $stp = $decode($stored('stp', [['kind'=>'bridge', 'instance'=>0, 'protocol'=>'rstp', 'bridge_id'=>'8000000000000001',
        'root_bridge_id'=>'8000000000000001', 'root_cost'=>0, 'root_port_uid'=>null, 'priority'=>32768, 'vlans'=>null,
        'topology_changes'=>3, 'topology_changed_at'=>'2026-11-24T11:00:00Z']]), 'stp', $now, $now);
    $assert($stp['data'][0]['time_since_topology_change_s'] === 3600, 'Time since the last topology change is restored.');

    $lldp = $decode($stored('lldp', [['local_interface_uid'=>'if-a1', 'local_port_id'=>['subtype'=>5, 'value'=>'Gi1'],
        'remote_chassis_id'=>['subtype'=>7, 'value'=>'chassis-2'], 'remote_port_id'=>['subtype'=>5, 'value'=>'Gi1'],
        'remote_management_addresses'=>[], 'remote_system_name'=>null]]), 'lldp', $now - 600, $now - 60);
    $assert($lldp['data'][0]['observed_at'] === $lldp['observed_at'], 'Each neighbour is observed with its snapshot.');

    $failed = $decode($stored('lldp', [], 'failed'), 'lldp', $now - 300, $now - 60);
    $assert($failed['observed_at'] === null && $failed['attempted_at'] === '2026-11-24T11:55:00Z',
        'A failure observes nothing, and was attempted when it was stored, whatever succeeded before.');
    $receipt = $decode($stored('lldp', []) + ['data_rows'=>4, 'data_omitted'=>true], 'lldp', $now - 900, $now - 60);
    $assert($receipt['status'] === 'ok' && $receipt['attempted_at'] === '2026-11-24T11:59:00Z',
        'A complete receipt was last attempted at the last complete observation.');

    // The reader: status, link and inventory walks of one host, each stored when it changed.
    $gateway = new StoredGateway();
    $port = static fn(string $uid, string $name, ?int $speed, ?string $duplex) => ['uid'=>$uid, 'if_index'=>1,
        'name'=>$name, 'physical'=>true, 'admin_status'=>'up', 'oper_status'=>'up', 'speed_bps'=>$speed,
        'duplex'=>$duplex];
    $gateway->add('1', 'ne.interfaces.state', [[$now - 7200, $stored('interfaces', [$port('if-a1', 'Gi1', null, null)])]]);
    $gateway->add('1', 'ne.interfaces.link', [[$now - 7200, $stored('interfaces', [$port('if-a1', 'Gi1', 100000000, 'full')])]]);
    $gateway->add('1', 'ne.interfaces.inventory', [[$now - 7200,
        $stored('interfaces', [$port('if-a1', 'Gi1', 1000000000, 'half')])]]);
    $gateway->add('1', 'ne.collection.success[interfaces]', [], 3, $now - 100);
    $gateway->add('1', 'ne.collection.success[interfaces.link]', [], 3, $now - 400);
    $gateway->add('1', 'ne.collection.success[interfaces.inventory]', [], 3, $now - 1000);
    $read = (new DatasetReader($gateway, $now))->read(['1'=>['hostid'=>'1']]);
    $interfaces = $read['datasets']['1']['interfaces'] ?? null;
    $assert($interfaces !== null && $interfaces['observed_at'] === gmdate('Y-m-d\TH:i:s\Z', $now - 100),
        'Interfaces are observed when the status walk last completed, though the snapshot was stored two hours ago.');
    $assert($interfaces['freshness'] === 'current', 'A snapshot unchanged for two hours is still current.');
    $assert($interfaces['data'][0]['speed_bps'] === 100000000 && $interfaces['data'][0]['duplex'] === 'full',
        'Speed and duplex come from the link walk, over the inventory and the null status values.');
    $quality = array_values(array_filter($read['quality'], static fn($q) => $q['dataset'] === 'interfaces'))[0];
    $assert($quality['observed_at'] === gmdate('Y-m-d\TH:i:s\Z', $now - 100), 'Quality reports the same observation.');

    $stale = new StoredGateway();
    $stale->add('1', 'ne.interfaces.state', [[$now - 7200, $stored('interfaces', [$port('if-a1', 'Gi1', null, null)])]]);
    $stale->add('1', 'ne.collection.success[interfaces]', [], 3, $now - 1000);
    $staleRead = (new DatasetReader($stale, $now))->read(['1'=>['hostid'=>'1']]);
    $assert($staleRead['datasets']['1']['interfaces']['freshness'] === 'stale',
        'Without a recent complete observation the snapshot is stale, though its value never changed.');
    $only = (new DatasetReader($gateway, $now))->read(['1'=>['hostid'=>'1']], ['ne.interfaces.state']);
    $assert(($only['datasets']['1']['interfaces']['observed_at'] ?? null) === gmdate('Y-m-d\TH:i:s\Z', $now - 100),
        'Reading one snapshot also reads its walk\'s last complete observation.');

    echo "Stored-envelope checks passed ({$checks} checks).\n";
})();
