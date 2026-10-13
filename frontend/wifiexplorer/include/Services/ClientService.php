<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Client journey (requirements section 13): the current clients of the visible clusters, a search over what the
 * viewer may already see, and for one selected client its trace (AP, radio, wired uplink, VLAN paths) and a
 * sampled association timeline.
 *
 * Privacy follows the producer's policy (full, partial or pseudonymised): the frontend shows exactly the
 * identifiers the snapshot holds and never derives more. A client is addressed by its opaque client_uid only.
 *
 * The timeline reads the client snapshot history over a bounded window. A change of AP or BSSID between two
 * samples is an association change observed between those samples, not an exact roam time: the client may have
 * moved more than once, or left and returned, in between.
 */
final class ClientService {
    private ?WifiHistory $history;
    private int $now;

    public function __construct(?WifiHistory $history, int $now) {
        $this->history = $history;
        $this->now = $now;
    }

    /**
     * @param array $owners   hostid => owner
     * @param array $datasets hostid => dataset => envelope
     * @param array $aps      ap_uid => AP
     */
    public function build(array $owners, array $datasets, array $aps, string $query, string $selected): array {
        $radios = [];
        $families = [];
        foreach ($aps as $ap) {
            foreach ($ap['radios'] as $radio) {
                if ($radio['bssid'] !== null) {
                    $radios[$radio['bssid']] = [$ap['ap_uid'], $radio['radio_uid']];
                    $families[substr($radio['bssid'], 0, 14)][$radio['radio_uid']] = $ap['ap_uid'];
                }
            }
        }
        $sources = [];
        $clients = [];
        foreach ($owners as $hostid => $owner) {
            $set = $datasets[$hostid]['client'] ?? null;
            if ($set === null) {
                continue;
            }
            $hostid = (string) $hostid;
            $policy = $set['data'][0]['identifiers'] ?? null;
            $sources[$hostid] = ['hostid'=>$hostid, 'name'=>$owner['name'], 'freshness'=>$set['freshness'] ?? 'unknown',
                'observed_at'=>$set['observed_at'] ?? null, 'clients'=>count($set['data']), 'policy'=>$policy,
                'over_limit'=>in_array('clients_over_limit', array_column($set['errors'] ?? [], 'code'), true),
                'unkeyed'=>in_array('client_key_missing', array_column($set['warnings'] ?? [], 'code'), true)];
            if (($set['freshness'] ?? 'unknown') !== 'current') {
                continue;   // A stale list is not "who is connected now".
            }
            foreach ($set['data'] as $row) {
                $clients[$row['client_uid']] = $this->client($row, $hostid, $aps, $radios, $families,
                    $set['observed_at'] ?? null);
            }
        }
        $needle = mb_strtolower(trim($query));
        $matched = $needle === '' ? $clients : array_filter($clients, function (array $c) use ($needle, $aps): bool {
            foreach ([$c['client_uid'], $c['mac_address'], $c['ip_address'], $c['name'], $c['bssid'],
                    $c['ap_uid'] !== null ? ($aps[$c['ap_uid']]['name'] ?? null) : null] as $field) {
                if ($field !== null && strpos(mb_strtolower((string) $field), $needle) !== false) {
                    return true;
                }
            }
            return false;
        });
        uasort($matched, static fn($a, $b) => [$a['ap_name'] ?? "\u{10FFFF}", $a['client_uid']]
            <=> [$b['ap_name'] ?? "\u{10FFFF}", $b['client_uid']]);
        $client = $selected !== '' ? ($clients[$selected] ?? null) : null;
        return ['sources'=>array_values($sources), 'total'=>count($clients), 'matched'=>count($matched),
            'clients'=>array_values(array_slice($matched, 0, WifiLimits::DISPLAY_CLIENTS)),
            'selected'=>$client, 'selection_missing'=>$selected !== '' && $client === null,
            'timeline'=>$client !== null ? $this->timeline($client, $aps) : null];
    }

    private function client(array $row, string $hostid, array $aps, array $radios, array $families, ?string $observed): array {
        $apUid = $row['ap_uid'];
        $radioUid = null;
        $radioBasis = null;
        if ($row['bssid'] !== null && isset($radios[$row['bssid']])) {
            [$bssidAp, $radioUid] = $radios[$row['bssid']];
            $radioBasis = 'bssid';
            $apUid = $apUid ?? $bssidAp;
        }
        elseif ($row['bssid'] !== null) {
            // Aruba derives each SSID's BSSID from the radio MAC: the same first five octets on the same AP.
            $candidates = array_filter($families[substr($row['bssid'], 0, 14)] ?? [], static fn($ap) => $ap === $apUid);
            if (count($candidates) === 1) {
                [$radioUid, $radioBasis] = [(string) array_key_first($candidates), 'bssid_family'];
            }
        }
        return ['client_uid'=>$row['client_uid'], 'mac_address'=>$row['mac_address'], 'ip_address'=>$row['ip_address'],
            'name'=>$row['name'], 'identifiers'=>$row['identifiers'], 'owner_hostid'=>$hostid,
            'ap_uid'=>$apUid !== null && isset($aps[$apUid]) ? $apUid : null, 'ap_basis'=>$row['ap_basis'],
            'ap_name'=>$apUid !== null ? ($aps[$apUid]['name'] ?? null) : null,
            'radio_uid'=>$radioUid, 'radio_basis'=>$radioBasis, 'bssid'=>$row['bssid'], 'snr_db'=>$row['snr_db'],
            'connected_s'=>$row['connected_s'], 'observed_at'=>$observed];
    }

    /**
     * Samples of this client's owner's snapshot history: where the client was in each, and the changes between
     * consecutive samples. Bounded by time, sample count and bytes; any bound reached is reported.
     */
    private function timeline(array $client, array $aps): array {
        $base = ['available'=>false, 'reason'=>null, 'window_s'=>WifiLimits::CLIENT_HISTORY_S, 'samples'=>[],
            'changes'=>[], 'bounded'=>false, 'kind'=>'sampled'];
        if ($this->history === null) {
            return ['reason'=>'history_unavailable'] + $base;
        }
        $rows = $this->history->window($client['owner_hostid'], 'we.client.snapshot', $this->now - WifiLimits::CLIENT_HISTORY_S,
            $this->now, WifiLimits::CLIENT_HISTORY_SAMPLES + 1, WifiLimits::CLIENT_HISTORY_BYTES);
        $bounded = count($rows) > WifiLimits::CLIENT_HISTORY_SAMPLES;
        $rows = array_slice($rows, 0, WifiLimits::CLIENT_HISTORY_SAMPLES);
        $validator = new WifiEnvelopeValidator();
        $bytes = 0;
        $samples = [];
        foreach ($rows as $row) {
            $bytes += strlen($row['value']);
            if ($bytes > WifiLimits::CLIENT_HISTORY_BYTES) {
                $bounded = true;
                break;
            }
            try {
                $envelope = $validator->decode($row['value'], 'client');
            }
            catch (\InvalidArgumentException $error) {
                continue;   // An invalid sample is skipped, not guessed at.
            }
            $found = null;
            foreach ($envelope['data'] as $entry) {
                if ($entry['client_uid'] === $client['client_uid']) {
                    $found = $entry;
                    break;
                }
            }
            $samples[] = ['clock'=>$row['clock'], 'observed_at'=>$envelope['observed_at'], 'present'=>$found !== null,
                'ap_uid'=>$found['ap_uid'] ?? null, 'bssid'=>$found['bssid'] ?? null, 'snr_db'=>$found['snr_db'] ?? null,
                'ap_name'=>isset($found['ap_uid']) ? ($aps[$found['ap_uid']]['name'] ?? null) : null];
        }
        $samples = array_reverse($samples);   // Oldest first.
        $changes = [];
        for ($i = 1; $i < count($samples); ++$i) {
            [$before, $after] = [$samples[$i - 1], $samples[$i]];
            $type = null;
            if ($before['present'] && !$after['present']) {
                $type = 'left';
            }
            elseif (!$before['present'] && $after['present']) {
                $type = 'appeared';
            }
            elseif ($before['present'] && $before['ap_uid'] !== $after['ap_uid']) {
                $type = 'ap_changed';
            }
            elseif ($before['present'] && $before['bssid'] !== $after['bssid']) {
                $type = 'bssid_changed';
            }
            if ($type !== null) {
                $changes[] = ['type'=>$type, 'between'=>[$before['clock'], $after['clock']], 'from_ap'=>$before['ap_uid'],
                    'to_ap'=>$after['ap_uid'], 'from_bssid'=>$before['bssid'], 'to_bssid'=>$after['bssid'], 'kind'=>'inferred'];
            }
        }
        return ['available'=>true, 'reason'=>$samples ? null : ($bounded ? 'history_too_large' : 'no_history'), 'samples'=>$samples, 'changes'=>$changes,
            'bounded'=>$bounded] + $base;
    }
}
