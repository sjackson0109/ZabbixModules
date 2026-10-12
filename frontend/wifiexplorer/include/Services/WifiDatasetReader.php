<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\DataGateway;
use Modules\NetworkExplorer\Services\DatasetQuality;
use Modules\NetworkExplorer\Services\Limits;

/**
 * Reads the Wi-Fi snapshots of permitted owner hosts through Network Explorer's gateway, with Network Explorer's
 * envelope and freshness rules: per item the last complete observation is kept, a newer failed or partial attempt
 * is reported but never replaces it, and staleness follows each dataset's template default.
 */
final class WifiDatasetReader {
    public const KEYS = ['we.device.snapshot'=>'device', 'we.ap.inventory'=>'ap_inventory', 'we.ap.state'=>'ap_state',
        'we.radio.inventory'=>'radio_inventory', 'we.radio.state'=>'radio_state'];
    public const ATTEMPTS = ['we.device.attempt'=>'device', 'we.ap.inventory.attempt'=>'ap_inventory',
        'we.ap.state.attempt'=>'ap_state', 'we.radio.inventory.attempt'=>'radio_inventory',
        'we.radio.state.attempt'=>'radio_state'];
    /** Every Wi-Fi producer carries the device dataset, so these keys alone find the owner hosts. */
    public const MEMBERSHIP = ['we.device.snapshot', 'we.device.attempt'];
    /** Seconds; matches the templates' {$WE.<DATASET>.STALE} defaults. */
    public const TTL = ['device'=>10800, 'ap_inventory'=>10800, 'ap_state'=>900, 'radio_inventory'=>10800,
        'radio_state'=>900];

    private DataGateway $gateway;
    private WifiEnvelopeValidator $validator;
    private int $now;

    public function __construct(DataGateway $gateway, ?int $now = null) {
        $this->gateway = $gateway;
        $this->validator = new WifiEnvelopeValidator();
        $this->now = $now ?? time();
    }

    /**
     * @param array $hosts hostid => host, each already returned by the gateway for the current user
     * @return array{datasets: array, quality: array, budgets: array}
     */
    public function read(array $hosts): array {
        $hostids = array_map('strval', array_keys($hosts));
        $items = $hostids ? $this->gateway->items($hostids,
            array_merge(array_keys(self::KEYS), array_keys(self::ATTEMPTS))) : [];
        if (count($items) > Limits::ITEMS) {
            throw new \RuntimeException('item_budget_exceeded');
        }
        $historyItems = [];
        foreach ($items as $item) {
            $key = (string) $item['key_'];
            // Canonical envelopes must be text history; anything else is not a Wi-Fi Explorer producer.
            if (isset($hosts[(string) $item['hostid']]) && (isset(self::KEYS[$key]) || isset(self::ATTEMPTS[$key]))
                    && (int) $item['value_type'] === ITEM_VALUE_TYPE_TEXT) {
                $historyItems[] = $item;
            }
        }
        if (count($historyItems) > Limits::HISTORY_ITEMS) {
            throw new \RuntimeException('history_budget_exceeded');
        }
        $history = $this->gateway->history($historyItems, 2);
        $records = [];
        $bytes = 0;
        foreach ($historyItems as $item) {
            $key = (string) $item['key_'];
            $dataset = self::KEYS[$key] ?? self::ATTEMPTS[$key];
            $latest = null;
            $success = null;
            $error = null;
            foreach ($history[(string) $item['itemid']] ?? [] as $row) {
                $value = (string) ($row['value'] ?? '');
                $bytes += strlen($value);
                if ($bytes > Limits::HISTORY_BYTES) {
                    throw new \RuntimeException('response_budget_exceeded');
                }
                try {
                    $envelope = $this->validator->decode($value, $dataset);
                    $latest = $latest ?? $envelope;
                    if ($envelope['status'] === 'ok' && $envelope['complete']) {
                        $success = $envelope;
                        break;
                    }
                }
                catch (\InvalidArgumentException $e) {
                    if ($latest === null) {
                        $error = $e->getMessage();
                    }
                }
            }
            $records[(string) $item['hostid']][$dataset][isset(self::KEYS[$key]) ? 'snapshot' : 'attempt'] = [
                'latest'=>$latest, 'success'=>$success, 'error'=>$error,
                'failure'=>(int) ($item['state'] ?? 0) !== 0 ? 'item_not_supported'
                    : ((int) ($item['status'] ?? 0) !== 0 ? 'item_disabled' : null)];
        }

        $datasets = [];
        $quality = [];
        foreach ($records as $hostid => $byDataset) {
            foreach ($byDataset as $dataset => $parts) {
                $snapshot = $parts['snapshot'] ?? null;
                $attemptRecord = $parts['attempt'] ?? null;
                $envelope = $snapshot['success'] ?? $snapshot['latest'] ?? $attemptRecord['success'] ?? null;
                $attempt = $attemptRecord['latest'] ?? $snapshot['latest'] ?? null;
                $failure = null;
                foreach ([$snapshot, $attemptRecord] as $record) {
                    if ($record !== null) {
                        $failure = $record['failure'] ?? $record['error'] ?? $failure;
                    }
                }
                // A timeout marks the SNMP interface unavailable and records no attempt at all.
                if (($attempt['source']['method'] ?? null) === 'native_snmp'
                        && ($hosts[$hostid]['snmp_available'] ?? null) === false) {
                    $failure = 'agent_unreachable';
                }
                $metadata = ['dataset'=>$dataset, 'hostid'=>(string) $hostid]
                    + DatasetQuality::describe($envelope, $attempt, $failure, self::TTL[$dataset], $this->now);
                $quality[] = $metadata;
                if ($envelope !== null) {
                    $envelope['freshness'] = $metadata['freshness'];
                    $datasets[$hostid][$dataset] = $envelope;
                }
            }
        }
        usort($quality, static fn($a, $b) => [(int) $a['hostid'], $a['dataset']] <=> [(int) $b['hostid'], $b['dataset']]);
        return ['datasets'=>$datasets, 'quality'=>$quality,
            'budgets'=>['history_items'=>count($historyItems), 'history_bytes'=>$bytes]];
    }
}
