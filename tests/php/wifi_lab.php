<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/wifiexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';
require_once __DIR__.'/services.php';

/**
 * The Wi-Fi lab as the frontend reads it: the real template normalisers run over the synthetic walks, with every
 * observation stamped at one pinned time so freshness is deterministic.
 *
 *   10 avc-west            the cluster's virtual controller (site lab-west)
 *   20 lab-ap-01           lab-ap-01 at its own address: RF detections and, with Network Explorer's LLDP, its uplink
 *   30 sw-wifi-dist-01     \
 *   31 sw-wifi-access-01    } Network Explorer switches (site lab-west, domain lab-wifi)
 *   32 sw-wifi-access-02   /
 */
final class WifiLab {
    public const NOW = '2026-10-12T12:00:00Z';
    public const OBSERVED = '2026-10-12T11:58:00Z';
    private const WIFI_RAW = ['device'=>'we.raw.aruba.system', 'ap_inventory'=>'we.raw.aruba.ap.inventory',
        'ap_state'=>'we.raw.aruba.ap.state', 'radio_inventory'=>'we.raw.aruba.radio.inventory',
        'radio_state'=>'we.raw.aruba.radio.state', 'ssid'=>'we.raw.aruba.ssid', 'client'=>'we.raw.aruba.client',
        'rf_neighbour'=>'we.raw.aruba.rf.neighbour'];
    private const NE_RAW = ['ne.raw.system'=>['ne.device.snapshot'], 'ne.raw.if.inventory'=>['ne.interfaces.inventory'],
        'ne.raw.if.state'=>['ne.interfaces.state'], 'ne.raw.lldp'=>['ne.lldp.snapshot'], 'ne.raw.vlan'=>['ne.vlan.snapshot'],
        'ne.raw.stp'=>['ne.stp.snapshot'], 'ne.raw.lag'=>['ne.lag.snapshot']];
    public const SWITCHES = ['30'=>['sw-wifi-dist-01', '192.0.2.200'], '31'=>['sw-wifi-access-01', '192.0.2.201'],
        '32'=>['sw-wifi-access-02', '192.0.2.202']];
    private static array $cache = [];

    public static function now(): int {
        return strtotime(self::NOW);
    }

    /** One normalised envelope, observed at $time. */
    public static function envelope(string $raw, string $walk, string $time = self::OBSERVED): array {
        $path = dirname(__DIR__).'/fixtures/wifi/walks/'.$walk;
        $key = $raw.'|'.$walk;
        if (!isset(self::$cache[$key])) {
            $out = shell_exec('node '.escapeshellarg(dirname(__DIR__).'/js/run_normaliser.cjs').' '.escapeshellarg($raw).' '
                .escapeshellarg($path));
            self::$cache[$key] = json_decode((string) $out, true, 512, JSON_THROW_ON_ERROR);
        }
        $envelope = self::$cache[$key];
        $envelope['attempted_at'] = $time;
        if ($envelope['observed_at'] !== null) {
            $envelope['observed_at'] = $time;
        }
        foreach ($envelope['data'] as &$row) {
            if (array_key_exists('observed_at', $row)) {
                $row['observed_at'] = $time;
            }
        }
        unset($row);
        return $envelope;
    }

    public static function host(string $id, string $name, string $site, string $address, array $tags = [],
            int $available = 1): array {
        $all = $site === '' ? [] : [['tag'=>'site', 'value'=>$site]];
        foreach ($tags as $tag => $value) {
            $all[] = ['tag'=>$tag, 'value'=>$value];
        }
        return ['hostid'=>$id, 'host'=>$name, 'name'=>$name, 'tags'=>$all, 'macros'=>[],
            'interfaces'=>[['type'=>2, 'useip'=>1, 'ip'=>$address, 'available'=>$available]]];
    }

    /**
     * Feeds a Wi-Fi owner's datasets as the templates store them: the attempt always (a complete one as a receipt
     * without its rows), the snapshot only for a complete observation.
     */
    public static function feedWifi(FixtureGateway $gateway, string $hostid, string $walk, array $datasets,
            string $time = self::OBSERVED): void {
        $snapshot = array_flip(\Modules\WifiExplorer\Services\WifiDatasetReader::KEYS);
        $attempt = array_flip(\Modules\WifiExplorer\Services\WifiDatasetReader::ATTEMPTS);
        foreach ($datasets as $dataset) {
            $envelope = self::envelope(self::WIFI_RAW[$dataset], $walk, $time);
            if ($envelope['status'] === 'ok' && $envelope['complete']) {
                $gateway->add($hostid, $attempt[$dataset], [['data_rows'=>count($envelope['data']), 'data'=>[],
                    'data_omitted'=>true] + $envelope]);
                $gateway->add($hostid, $snapshot[$dataset], [$envelope]);
            }
            else {
                $gateway->add($hostid, $attempt[$dataset], [$envelope]);
            }
        }
    }

    public static function feedNetwork(FixtureGateway $gateway, string $hostid, string $walk, array $only = [],
            string $time = self::OBSERVED): void {
        foreach (self::NE_RAW as $raw => $keys) {
            if ($only && !in_array($raw, $only, true)) {
                continue;
            }
            foreach ($keys as $key) {
                $gateway->add($hostid, $key, [self::envelope($raw, $walk, $time)]);
            }
        }
    }

    /** The whole lab. $omit leaves hosts out (for example to hide a switch from the viewer). */
    public static function gateway(array $omit = []): FixtureGateway {
        $gateway = new FixtureGateway();
        $hosts = ['10'=>self::host('10', 'avc-west', 'lab-west', '192.0.2.10'),
            '20'=>self::host('20', 'lab-ap-01', 'lab-west', '192.0.2.250', ['ne.domain'=>'lab-wifi'])];
        foreach (self::SWITCHES as $id => [$name, $address]) {
            $hosts[$id] = self::host((string) $id, $name, 'lab-west', $address, ['ne.domain'=>'lab-wifi']);
        }
        foreach ($omit as $id) {
            unset($hosts[$id]);
        }
        $gateway->hostRows = array_values($hosts);
        // Items exist whether or not the viewer can read the host: the gateway must still never return them.
        self::feedWifi($gateway, '10', 'aruba-instant-vc.snmprec', array_keys(self::WIFI_RAW));
        self::feedWifi($gateway, '20', 'aruba-instant-ap-01.snmprec', ['rf_neighbour']);
        self::feedNetwork($gateway, '20', 'aruba-instant-ap-01.snmprec', ['ne.raw.lldp']);
        foreach (self::SWITCHES as $id => [$name]) {
            self::feedNetwork($gateway, (string) $id, $name.'.snmprec');
        }
        return $gateway;
    }

    public static function config(): array {
        $uid = static fn(int $n): string => 'ap-'.substr(hash('sha256', 'ap:00:00:5e:00:53:'.sprintf('%02x', $n)), 0, 24);
        return \Modules\WifiExplorer\Services\WifiConfig::normalise([
            'version'=>1,
            'floors'=>[['floor_id'=>'west-ground', 'site'=>'lab-west', 'building'=>'Main', 'name'=>'Ground floor',
                    'order'=>0, 'aspect'=>0.5, 'width_m'=>60],
                ['floor_id'=>'west-first', 'site'=>'lab-west', 'building'=>'Main', 'name'=>'First floor', 'order'=>1,
                    'aspect'=>0.5],
                ['floor_id'=>'east-ground', 'site'=>'lab-east', 'name'=>'East ground', 'aspect'=>0.5]],
            'placements'=>[$uid(1)=>['floor_id'=>'west-ground', 'x'=>0.2, 'y'=>0.3],
                $uid(2)=>['floor_id'=>'west-ground', 'x'=>0.5, 'y'=>0.3],
                $uid(4)=>['floor_id'=>'west-ground', 'x'=>0.8, 'y'=>0.7],
                $uid(5)=>['floor_id'=>'west-first', 'x'=>0.5, 'y'=>0.5]],
            'ssids'=>[['ssid'=>'Lab-Corp', 'site'=>'lab-west', 'vlan'=>49],
                ['ssid'=>'Lab-Event', 'site'=>'lab-west', 'vlan'=>56, 'bands'=>['5', '6']],
                ['ssid'=>'Lab-Guest', 'site'=>'lab-west', 'vlan'=>57, 'expect'=>'floors', 'floors'=>['west-ground']],
                ['ssid'=>'Lab-Expected', 'site'=>'lab-west', 'vlan'=>58]],
            'events'=>[['event_id'=>'expo', 'name'=>'Expo', 'site'=>'lab-west', 'ssid'=>'Lab-Event',
                'starts'=>'2026-10-20T08:00:00Z', 'ends'=>'2026-10-20T18:00:00Z', 'min_aps'=>4,
                'expected_clients'=>100, 'clients_per_ap'=>30]],
            'known_bssids'=>[['bssid'=>'00:00:5e:00:53:f4', 'label'=>'Neighbouring office']]
        ]);
    }

    public static function apUid(int $n): string {
        return 'ap-'.substr(hash('sha256', 'ap:00:00:5e:00:53:'.sprintf('%02x', $n)), 0, 24);
    }
}
