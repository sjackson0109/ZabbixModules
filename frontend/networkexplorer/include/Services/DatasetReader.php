<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

final class DatasetReader {
    public const KEYS = [
        'ne.device.snapshot'=>'device', 'ne.interfaces.inventory'=>'interfaces',
        'ne.interfaces.state'=>'interfaces', 'ne.lldp.snapshot'=>'lldp', 'ne.lag.snapshot'=>'lag'
    ];
    private const ATTEMPTS = ['ne.device.attempt'=>'device', 'ne.interfaces.attempt'=>'interfaces',
        'ne.lldp.attempt'=>'lldp', 'ne.lag.attempt'=>'lag'];
    private const TTL = ['device'=>172800, 'interfaces'=>180, 'lldp'=>900, 'lag'=>900];
    private DataGateway $gateway;
    private EnvelopeValidator $validator;
    private int $now;

    public function __construct(DataGateway $gateway, ?int $now = null) {
        $this->gateway = $gateway;
        $this->validator = new EnvelopeValidator();
        $this->now = $now ?? time();
    }

    public function read(array $hosts): array {
        $items = $this->gateway->items(array_map('strval', array_keys($hosts)));
        if (count($items) > 50000) {
            throw new \RuntimeException('item_budget_exceeded');
        }
        $historyItems = [];
        $scalarItemIds = [];
        foreach ($items as $item) {
            if (!isset($hosts[(string) $item['hostid']])) {
                continue;
            }
            $key = (string) $item['key_'];
            if (isset(self::KEYS[$key]) || isset(self::ATTEMPTS[$key])) {
                // Canonical envelopes MUST be text history, never guessed as uint.
                if ((int) $item['value_type'] === 4) {
                    $historyItems[] = $item;
                }
            }
            elseif (preg_match('/^ne\.if\.oper\[([A-Za-z0-9_.:-]{1,128})\]$/D', $key, $match)) {
                $scalarItemIds[(string) $item['hostid']][$match[1]] = (string) $item['itemid'];
            }
        }
        if (count($historyItems) > 3000) {
            throw new \RuntimeException('history_budget_exceeded');
        }
        $history = $this->gateway->history($historyItems, 2);
        $byHost = [];
        $byteCount = 0;
        foreach ($historyItems as $item) {
            $hostid = (string) $item['hostid'];
            $key = (string) $item['key_'];
            $dataset = self::KEYS[$key] ?? self::ATTEMPTS[$key];
            $latest = null;
            $success = null;
            $error = null;
            foreach ($history[(string) $item['itemid']] ?? [] as $row) {
                $value = (string) ($row['value'] ?? '');
                $byteCount += strlen($value);
                if ($byteCount > 67108864) {
                    throw new \RuntimeException('response_budget_exceeded');
                }
                try {
                    $envelope = $this->validator->decode($value, $dataset);
                    if ($latest === null) {
                        $latest = $envelope;
                    }
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
            $byHost[$hostid][$key] = ['latest'=>$latest, 'success'=>$success,
                'error'=>$error, 'native_failed'=>(int) ($item['state'] ?? 0) !== 0,
                'disabled'=>(int) ($item['status'] ?? 0) !== 0];
        }
        $datasets = [];
        $quality = [];
        foreach ($hosts as $hostid => $host) {
            foreach (['device','interfaces','lldp','lag'] as $dataset) {
                $records = $byHost[$hostid] ?? [];
                $keys = array_keys(array_filter(self::KEYS, fn($value) => $value === $dataset));
                $parts = [];
                $failure = null;
                foreach ($keys as $key) {
                    $record = $records[$key] ?? null;
                    if ($record !== null) {
                        if ($record['error'] !== null) {
                            $failure = $record['error'];
                        }
                        if ($record['native_failed']) {
                            $failure = 'item_not_supported';
                        }
                        if ($record['disabled']) {
                            $failure = 'item_disabled';
                        }
                        if ($record['success'] !== null || $record['latest'] !== null) {
                            $parts[$key] = $record['success'] ?? $record['latest'];
                        }
                    }
                }
                $attemptKey = array_search($dataset, self::ATTEMPTS, true);
                $attempt = $records[$attemptKey]['latest'] ?? null;
                foreach ($keys as $key) {
                    $candidate = $records[$key]['latest'] ?? null;
                    if ($candidate !== null && ($attempt === null
                            || strtotime($candidate['attempted_at']) > strtotime($attempt['attempted_at']))) {
                        $attempt = $candidate;
                    }
                }
                $attemptError = $records[$attemptKey]['error'] ?? null;
                if ($attemptError !== null) {
                    $failure = $attemptError;
                }
                if ($records[$attemptKey]['native_failed'] ?? false) {
                    $failure = 'item_not_supported';
                }
                if ($records[$attemptKey]['disabled'] ?? false) {
                    $failure = 'item_disabled';
                }
                $envelope = $this->merge($parts, $dataset);
                $metadata = $this->quality($envelope, $attempt, $dataset, $failure);
                $metadata['hostid'] = (string) $hostid;
                $quality[] = $metadata;
                if ($envelope !== null) {
                    $envelope['freshness'] = $metadata['freshness'];
                    $datasets[$hostid][$dataset] = $envelope;
                }
            }
        }
        return ['datasets'=>$datasets, 'quality'=>$quality, 'itemids'=>$scalarItemIds,
            'budgets'=>['history_items'=>count($historyItems), 'history_bytes'=>$byteCount,
                'host_limit'=>300, 'interface_limit'=>30000]];
    }

    private function merge(array $parts, string $dataset): ?array {
        if (!$parts) {
            return null;
        }
        if ($dataset !== 'interfaces') {
            return reset($parts);
        }
        $inventory = $parts['ne.interfaces.inventory'] ?? null;
        $state = $parts['ne.interfaces.state'] ?? null;
        $merged = $state ?? $inventory;
        $rows = [];
        foreach (($inventory['data'] ?? []) as $row) {
            // Inventory metadata does not refresh operational observations for an
            // interface absent from the latest state snapshot.
            $row['_state_present'] = false;
            $rows[$row['uid']] = $row;
        }
        foreach (($state['data'] ?? []) as $row) {
            // Never pair a reused ifIndex with an unrelated UID.
            $rows[$row['uid']] = array_replace($rows[$row['uid']] ?? [], $row);
            $rows[$row['uid']]['_state_present'] = true;
        }
        $merged['data'] = array_values($rows);
        if ($inventory !== null) {
            $merged['inventory_observed_at'] = $inventory['observed_at'];
            $merged['inventory_stale'] = strtotime((string) $inventory['observed_at']) < $this->now - 7200;
        }
        return $merged;
    }

    private function quality(?array $envelope, ?array $attempt, string $dataset, ?string $failure): array {
        $observed = $envelope['observed_at'] ?? null;
        $epoch = $observed !== null ? strtotime($observed) : false;
        $freshness = 'unknown';
        $errors = [];
        if ($epoch !== false) {
            if ($epoch > $this->now + 60) {
                $errors[] = 'clock_skew';
            }
            else {
                $freshness = $this->now - $epoch > self::TTL[$dataset] ? 'stale' : 'current';
            }
        }
        $latest = $attempt !== null && ($envelope === null
            || strtotime($attempt['attempted_at']) >= strtotime($envelope['attempted_at']))
            ? $attempt : $envelope;
        $status = $latest['status'] ?? 'unknown';
        if ($failure !== null) {
            $status = 'failed';
            $errors[] = $failure;
        }
        foreach (($latest['errors'] ?? []) as $error) {
            // Raw device/collector exception strings may contain hidden peer data.
            // Only stable bounded error identifiers are returned to the browser.
            $code = is_array($error) ? ($error['code'] ?? null) : $error;
            if (is_string($code) && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $code)) {
                $errors[] = $code;
            }
        }
        if ($envelope['inventory_stale'] ?? false) {
            $errors[] = 'inventory_stale';
        }
        return ['dataset'=>$dataset, 'status'=>$status,
            'capability'=>$latest['capability']['state'] ?? 'unknown', 'freshness'=>$freshness,
            'attempted_at'=>$latest['attempted_at'] ?? null, 'observed_at'=>$observed,
            'age_seconds'=>$epoch !== false ? max(0, $this->now - $epoch) : null,
            'complete'=>$envelope['complete'] ?? false, 'retained'=> $envelope !== null
                && $latest !== null && $latest['status'] !== 'ok',
            'errors'=>array_values(array_unique($errors))];
    }
}
