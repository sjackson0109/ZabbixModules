<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Neighbouring and rogue access points as the visible APs detect them (requirements section 14).
 *
 * Each detection is owned by the AP that heard it. A BSSID heard by several APs is one row with every observer and
 * its SNR; the strongest observer is reported as "heard best at", which is evidence of proximity, not a location.
 * Classification is evidence-driven and configurable:
 *
 *   managed         the BSSID is a visible managed radio (observed), or shares its first five octets with one
 *                   (inferred: Aruba derives each SSID's BSSID from the radio MAC);
 *   known_external  an operator listed it as known (configuration);
 *   known_neighbour the detecting AP labels it valid or known-interfering;
 *   flagged         the detecting AP labels it unsecure, dos or suspected-unsecure;
 *   unknown         anything else.
 *
 * Nothing is called malicious: a flagged network is reported with the AP's own words and the evidence.
 */
final class RfService {
    /** SNR (dB) at or above which a same-channel network is strong enough to contend for airtime. */
    public const CONTENTION_SNR = 25;
    /** Rows the neighbour table shows; the rest are counted. */
    public const DISPLAY_NEIGHBOURS = 300;
    private const FLAGGED = ['unsecure', 'dos', 'suspected_unsecure'];
    private const KNOWN = ['valid', 'known_interfering'];

    /**
     * @param array $owners   hostid => owner (with addresses and name)
     * @param array $datasets hostid => dataset => envelope
     * @param array $aps      ap_uid => AP (with radios)
     * @param array $known    bssid => ['bssid', 'label'] from configuration
     */
    public function build(array $owners, array $datasets, array $aps, array $known): array {
        $managed = [];
        $family = [];
        foreach ($aps as $ap) {
            foreach ($ap['radios'] as $radio) {
                if ($radio['bssid'] !== null) {
                    $managed[$radio['bssid']] = ['ap_uid'=>$ap['ap_uid'], 'radio_uid'=>$radio['radio_uid']];
                    $family[substr($radio['bssid'], 0, 14)][$ap['ap_uid']] = $radio['radio_uid'];
                }
            }
        }
        $observers = [];
        $neighbours = [];
        foreach ($owners as $hostid => $owner) {
            $set = $datasets[$hostid]['rf_neighbour'] ?? null;
            if ($set === null) {
                continue;
            }
            [$apUid, $basis] = self::attribute($owner, $aps);
            $current = ($set['freshness'] ?? 'unknown') === 'current';
            $observers[(string) $hostid] = ['hostid'=>(string) $hostid, 'name'=>$owner['name'], 'ap_uid'=>$apUid,
                'basis'=>$basis, 'observed_at'=>$set['observed_at'] ?? null, 'freshness'=>$set['freshness'] ?? 'unknown',
                'detections'=>count($set['data']), 'bounded'=>in_array('neighbours_bounded',
                    array_column($set['warnings'] ?? [], 'code'), true), 'counts'=>[]];
            foreach ($set['data'] as $row) {
                $bssid = $row['bssid'];
                if (isset($managed[$bssid]) && $managed[$bssid]['ap_uid'] === $apUid) {
                    continue;   // An AP hearing its own radio is not a neighbour.
                }
                $class = $this->classify($row, $managed, $family, $known, $apUid);
                $observers[(string) $hostid]['counts'][$class[0]] = ($observers[(string) $hostid]['counts'][$class[0]] ?? 0) + 1;
                $entry = &$neighbours[$bssid];
                if ($entry === null) {
                    $entry = ['bssid'=>$bssid, 'ssid'=>$row['ssid'], 'channel'=>$row['channel'], 'band'=>$row['band'],
                        'channel_width'=>$row['channel_width'], 'encryption'=>$row['encryption'], 'class'=>$class[0],
                        'class_basis'=>$class[1], 'managed_ap_uid'=>$class[2], 'labels'=>[], 'observers'=>[],
                        'best_snr'=>null, 'heard_best_by'=>null, 'known_label'=>$known[$bssid]['label'] ?? null,
                        'current'=>false];
                }
                $label = $row['classification'] ?? null;
                if ($label !== null) {
                    $entry['labels'][$label === 'other' ? (string) ($row['classification_raw'] ?? 'other') : $label] = true;
                }
                $entry['observers'][] = ['hostid'=>(string) $hostid, 'ap_uid'=>$apUid, 'snr_db'=>$row['snr_db'],
                    'channel'=>$row['channel'], 'freshness'=>$set['freshness'] ?? 'unknown',
                    'observed_at'=>$set['observed_at'] ?? null];
                $entry['current'] = $entry['current'] || $current;
                if ($row['snr_db'] !== null && ($entry['best_snr'] === null || $row['snr_db'] > $entry['best_snr'])) {
                    $entry['best_snr'] = $row['snr_db'];
                    $entry['heard_best_by'] = $apUid ?? 'host:'.$hostid;
                }
                // A flagged label from any observer is kept: one AP's evidence is not overruled by another's silence.
                if ($class[0] === 'flagged' || $entry['class'] === 'unknown' && $class[0] !== 'unknown') {
                    [$entry['class'], $entry['class_basis'], $entry['managed_ap_uid']] = $class;
                }
                unset($entry);
            }
        }
        $list = array_values($neighbours);
        usort($list, static fn($a, $b) => [self::rank($a['class']), -($a['best_snr'] ?? -1), $a['bssid']]
            <=> [self::rank($b['class']), -($b['best_snr'] ?? -1), $b['bssid']]);
        $counts = array_fill_keys(['managed', 'known_external', 'known_neighbour', 'flagged', 'unknown'], 0);
        foreach ($list as $row) {
            ++$counts[$row['class']];
        }
        return ['observers'=>$observers, 'neighbours'=>array_slice($list, 0, self::DISPLAY_NEIGHBOURS),
            'total'=>count($list), 'counts'=>$counts, 'findings'=>$this->findings($list, $observers, $aps)];
    }

    /**
     * The AP a per-AP host observes: the AP whose address the host polls, else the one AP named like the host.
     * @return array{0: ?string, 1: ?string} AP ID and basis (address, host_name), or nulls
     */
    public static function attribute(array $owner, array $aps): array {
        $byAddress = [];
        $byName = [];
        foreach ($aps as $ap) {
            if ($ap['ip_address'] !== null) {
                $byAddress[$ap['ip_address']][] = $ap['ap_uid'];
            }
            if ($ap['name'] !== null) {
                $byName[strtolower($ap['name'])][] = $ap['ap_uid'];
            }
        }
        foreach ($owner['addresses'] ?? [] as $address) {
            if (count($byAddress[$address] ?? []) === 1) {
                return [$byAddress[$address][0], 'address'];
            }
        }
        $name = strtolower((string) ($owner['name'] ?? ''));
        return count($byName[$name] ?? []) === 1 ? [$byName[$name][0], 'host_name'] : [null, null];
    }

    /** @return array{0: string, 1: string, 2: ?string} class, basis, managed AP */
    private function classify(array $row, array $managed, array $family, array $known, ?string $observer): array {
        $bssid = $row['bssid'];
        if (isset($managed[$bssid])) {
            return ['managed', 'observed', $managed[$bssid]['ap_uid']];
        }
        $siblings = array_diff_key($family[substr($bssid, 0, 14)] ?? [], $observer !== null ? [$observer=>true] : []);
        if (count($siblings) === 1) {
            return ['managed', 'inferred', (string) array_key_first($siblings)];
        }
        if (isset($known[$bssid])) {
            return ['known_external', 'configured', null];
        }
        $label = $row['classification'] ?? null;
        if (in_array($label, self::FLAGGED, true)) {
            return ['flagged', 'observed', null];
        }
        if (in_array($label, self::KNOWN, true)) {
            return ['known_neighbour', 'observed', null];
        }
        return ['unknown', 'observed', null];
    }

    private static function rank(string $class): int {
        return ['flagged'=>0, 'unknown'=>1, 'known_neighbour'=>2, 'known_external'=>3, 'managed'=>4][$class];
    }

    /**
     * Flagged networks, and contention backed by RF evidence: an up radio whose own AP hears another network on
     * the same channel at CONTENTION_SNR or more. Channel equality alone is never a finding.
     */
    private function findings(array $neighbours, array $observers, array $aps): array {
        $findings = [];
        foreach ($neighbours as $row) {
            if ($row['class'] !== 'flagged' || !$row['current']) {
                continue;
            }
            $evidence = array_map(static fn($o) => ['dataset'=>'rf_neighbour', 'hostid'=>$o['hostid'],
                'observed_at'=>$o['observed_at'], 'fact'=>'SNR '.($o['snr_db'] ?? '?').' dB'], $row['observers']);
            $first = $row['observers'][0];
            $findings[] = WifiFinding::create('wifi_rf_flagged', 'warning', $first['hostid'], 'bssid', $row['bssid'],
                _s('%1$s (%2$s) is flagged as %3$s', $row['ssid'] ?? _('Hidden network'), $row['bssid'],
                    implode(', ', array_map(static fn($l) => str_replace('_', ' ', $l), array_keys($row['labels'])))),
                _s('Detected by %1$s AP(s). This is the detecting AP\'s own classification, evidence to investigate rather than a verdict.',
                    count($row['observers'])),
                $evidence, 'current',
                _('Locate it near the AP that hears it best, then decide: add it to the known BSSIDs, or investigate it.'));
        }
        foreach ($observers as $observer) {
            $ap = $observer['ap_uid'] !== null ? ($aps[$observer['ap_uid']] ?? null) : null;
            if ($ap === null || $observer['freshness'] !== 'current') {
                continue;
            }
            foreach ($ap['radios'] as $radio) {
                if ($radio['status'] !== 'up' || $radio['channel'] === null) {
                    continue;
                }
                $loud = [];
                foreach ($neighbours as $row) {
                    foreach ($row['observers'] as $o) {
                        if ($o['hostid'] === $observer['hostid'] && $o['channel'] === $radio['channel']
                                && $o['snr_db'] !== null && $o['snr_db'] >= self::CONTENTION_SNR) {
                            $loud[] = $row;
                        }
                    }
                }
                if (!$loud) {
                    continue;
                }
                $managed = array_filter($loud, static fn($r) => $r['class'] === 'managed');
                $name = ($ap['name'] ?? $ap['ap_uid']).' '._s('radio %1$s', $radio['radio_index'] ?? '?');
                $findings[] = WifiFinding::create($managed ? 'wifi_co_channel_managed' : 'wifi_co_channel_external',
                    'info', $observer['hostid'], 'radio', $radio['radio_uid'],
                    _s('%1$s shares channel %2$s with %3$s network(s) it hears at %4$s dB or more', $name,
                        $radio['channel'], count($loud), self::CONTENTION_SNR),
                    $managed
                        ? _('Another visible AP is on the same channel and this AP hears it strongly. Co-channel contention is likely; check the channel plan.')
                        : _('A network outside the visible inventory is on the same channel and heard strongly. Co-channel contention is likely.'),
                    array_map(static fn($r) => ['dataset'=>'rf_neighbour', 'hostid'=>$observer['hostid'],
                        'observed_at'=>$observer['observed_at'], 'fact'=>($r['ssid'] ?? $r['bssid']).' channel '
                        .$radio['channel']], array_slice($loud, 0, 5)),
                    'current', null, 'observed');
            }
        }
        return $findings;
    }
}
