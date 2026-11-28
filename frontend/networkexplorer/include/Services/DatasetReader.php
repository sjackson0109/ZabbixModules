<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

final class DatasetReader {
    public const KEYS = [
        'ne.device.snapshot'=>'device', 'ne.interfaces.inventory'=>'interfaces',
        'ne.interfaces.state'=>'interfaces', 'ne.interfaces.link'=>'interfaces', 'ne.lldp.snapshot'=>'lldp',
        'ne.lag.snapshot'=>'lag', 'ne.port_capability.snapshot'=>'port_capability', 'ne.vlan.snapshot'=>'vlan',
        'ne.stp.snapshot'=>'stp'
    ];
    // Native templates poll interface inventory, status and link (speed, duplex) as separate attempts.
    private const ATTEMPTS = ['ne.device.attempt'=>'device', 'ne.interfaces.attempt'=>'interfaces',
        'ne.interfaces.inventory.attempt'=>'interfaces', 'ne.interfaces.link.attempt'=>'interfaces',
        'ne.lldp.attempt'=>'lldp', 'ne.lag.attempt'=>'lag', 'ne.port_capability.attempt'=>'port_capability',
        'ne.vlan.attempt'=>'vlan', 'ne.stp.attempt'=>'stp'];
    /**
     * The walk (producer) each snapshot and attempt comes from. Its ne.collection.success[<producer>] item is stored at
     * every complete observation, so its Zabbix timestamp is when a stored-on-change snapshot was last confirmed.
     */
    private const PRODUCERS = ['ne.device.snapshot'=>'device', 'ne.device.attempt'=>'device',
        'ne.interfaces.state'=>'interfaces', 'ne.interfaces.attempt'=>'interfaces',
        'ne.interfaces.inventory'=>'interfaces.inventory', 'ne.interfaces.inventory.attempt'=>'interfaces.inventory',
        'ne.interfaces.link'=>'interfaces.link', 'ne.interfaces.link.attempt'=>'interfaces.link',
        'ne.lldp.snapshot'=>'lldp', 'ne.lldp.attempt'=>'lldp', 'ne.lag.snapshot'=>'lag', 'ne.lag.attempt'=>'lag',
        'ne.port_capability.snapshot'=>'port_capability', 'ne.port_capability.attempt'=>'port_capability',
        'ne.vlan.snapshot'=>'vlan', 'ne.vlan.attempt'=>'vlan', 'ne.stp.snapshot'=>'stp', 'ne.stp.attempt'=>'stp'];
    // Matches the native templates' {$NE.<DATASET>.STALE} defaults (interfaces: the status walk).
    private const TTL = ['device'=>172800, 'interfaces'=>450, 'lldp'=>2700, 'lag'=>2700,
        'port_capability'=>64800, 'vlan'=>5400, 'stp'=>900];
    /** Interface attributes owned by the inventory walk, not the state walk. */
    private const INVENTORY_FIELDS = ['description','alias','type','physical','mtu','mac_address','stack_parent_uid',
        'member','slot','port'];
    /** Interface attributes the native link walk owns; the status walk leaves them null. */
    private const LINK_FIELDS = ['speed_bps','duplex'];
    /** Always reported; the 1.1 datasets are reported only where a host has their items. */
    private const CORE = ['device','interfaces','lldp','lag'];
    /** A host with any of these is a Network Explorer host; every native template and the collector carry one. */
    public const MEMBERSHIP = ['ne.device.snapshot', 'ne.interfaces.inventory', 'ne.interfaces.state'];
    /** What peer identity needs from a host that is not drawn: who it is, and whose LLDP names a drawn switch. */
    public const IDENTITY = ['ne.device.snapshot', 'ne.lldp.snapshot'];
    private DataGateway $gateway;
    private EnvelopeValidator $validator;
    private int $now;

    public function __construct(DataGateway $gateway, ?int $now = null) {
        $this->gateway = $gateway;
        $this->validator = new EnvelopeValidator();
        $this->now = $now ?? time();
    }

    /**
     * Reads the hosts' snapshots. With $only (item keys), only those snapshot items (plus the membership keys, to tell which
     * hosts are Network Explorer hosts) are listed and read, and only their datasets are reported.
     */
    public function read(array $hosts, array $only = []): array {
        $hostids = array_map('strval', array_keys($hosts));
        $successKeys = array_map(static fn($key) => 'ne.collection.success['.self::PRODUCERS[$key].']',
            array_filter($only, static fn($key) => isset(self::PRODUCERS[$key])));
        $items = $hostids ? $this->gateway->items($hostids,
            $only ? array_values(array_unique(array_merge($only, self::MEMBERSHIP, $successKeys))) : []) : [];
        $wanted = $only ? array_fill_keys($only, true) : null;
        if (count($items) > Limits::ITEMS) {
            throw new \RuntimeException('item_budget_exceeded');
        }
        $historyItems = [];
        $scalarItemIds = [];
        $collected = [];
        $observed = [];
        foreach ($items as $item) {
            if (!isset($hosts[(string) $item['hostid']])) {
                continue;
            }
            $collected[(string) $item['hostid']] = true;
            $key = (string) $item['key_'];
            // When each walk last completed: Zabbix's own timestamp of its last complete observation.
            if (preg_match('/^ne\.collection\.success\[([a-z_.]{1,64})\]$/D', $key, $match)) {
                if ((int) ($item['lastclock'] ?? 0) > 0) {
                    $observed[(string) $item['hostid']][$match[1]] = (int) $item['lastclock'];
                }
                continue;
            }
            if ($wanted !== null && !isset($wanted[$key])) {
                continue;
            }
            if (isset(self::KEYS[$key]) || isset(self::ATTEMPTS[$key])) {
                // Canonical envelopes MUST be text history, never guessed as uint.
                if ((int) $item['value_type'] === ITEM_VALUE_TYPE_TEXT) {
                    $historyItems[] = $item;
                }
            }
            elseif (preg_match('/^ne\.if\.oper\[([A-Za-z0-9_.:-]{1,128})\]$/D', $key, $match)) {
                $scalarItemIds[(string) $item['hostid']][$match[1]] = (string) $item['itemid'];
            }
        }
        if (count($historyItems) > Limits::HISTORY_ITEMS) {
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
            // The newest stored value has been confirmed by every complete observation since it was stored.
            $confirmed = $observed[$hostid][self::PRODUCERS[$key] ?? ''] ?? null;
            foreach (array_values($history[(string) $item['itemid']] ?? []) as $index => $row) {
                $value = (string) ($row['value'] ?? '');
                $byteCount += strlen($value);
                if ($byteCount > Limits::HISTORY_BYTES) {
                    throw new \RuntimeException('response_budget_exceeded');
                }
                $value = StoredEnvelope::rehydrate($value, (int) ($row['clock'] ?? 0), $index === 0 ? $confirmed : null);
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
        $reported = $wanted === null ? array_keys(self::TTL) : array_values(array_unique(array_map(
            static fn($key) => self::KEYS[$key] ?? self::ATTEMPTS[$key], array_keys($wanted))));
        foreach ($hosts as $hostid => $host) {
            foreach ($reported as $dataset) {
                $records = $byHost[$hostid] ?? [];
                $keys = array_keys(array_filter(self::KEYS, fn($value) => $value === $dataset));
                $attemptKeys = array_keys(array_filter(self::ATTEMPTS, fn($value) => $value === $dataset));
                $own = array_intersect_key($records, array_flip(array_merge($keys, $attemptKeys)));
                // An optional dataset whose items are all disabled (Port Capability ships that way) is not collected,
                // so it has no outcome to report. A core dataset turned off still is one.
                if (!in_array($dataset, self::CORE, true)
                        && !array_filter($own, static fn(array $record): bool => !$record['disabled'])) {
                    continue;
                }
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
                $attempt = null;
                foreach (array_merge($attemptKeys, $keys) as $key) {
                    $candidate = $records[$key]['latest'] ?? null;
                    if ($candidate !== null && ($attempt === null
                            || strtotime($candidate['attempted_at']) > strtotime($attempt['attempted_at']))) {
                        $attempt = $candidate;
                    }
                }
                foreach ($attemptKeys as $attemptKey) {
                    if (($records[$attemptKey]['error'] ?? null) !== null) {
                        $failure = $records[$attemptKey]['error'];
                    }
                    if ($records[$attemptKey]['native_failed'] ?? false) {
                        $failure = 'item_not_supported';
                    }
                    if ($records[$attemptKey]['disabled'] ?? false) {
                        $failure = 'item_disabled';
                    }
                }
                // A timeout makes Zabbix mark the SNMP interface unavailable and
                // process no value, so no failed attempt is ever recorded for it.
                $native = ($attempt['source']['method'] ?? null) === 'native_snmp';
                if ($native && ($host['snmp_available'] ?? null) === false) {
                    $failure = 'agent_unreachable';
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
        return ['datasets'=>$datasets, 'quality'=>$quality, 'itemids'=>$scalarItemIds, 'collected'=>$collected,
            'budgets'=>['history_items'=>count($historyItems), 'history_bytes'=>$byteCount,
                'display_host_limit'=>Limits::DISPLAY_HOSTS, 'candidate_host_limit'=>Limits::CANDIDATE_HOSTS,
                'interface_limit'=>Limits::INTERFACES]];
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
        $link = $parts['ne.interfaces.link'] ?? null;
        $merged = $state ?? $inventory;
        $rows = [];
        foreach (($inventory['data'] ?? []) as $row) {
            // Inventory metadata does not refresh operational observations for an
            // interface absent from the latest state snapshot.
            $row['_state_present'] = false;
            $rows[$row['uid']] = $row;
        }
        foreach (($state['data'] ?? []) as $row) {
            // Native state walks leave inventory attributes null, and since 2.3.0 the link walk's speed and duplex
            // too; a null must not erase a value another walk reported.
            foreach (array_merge($inventory !== null ? self::INVENTORY_FIELDS : [], self::LINK_FIELDS) as $field) {
                if (array_key_exists($field, $row) && $row[$field] === null) {
                    unset($row[$field]);
                }
            }
            // Never pair a reused ifIndex with an unrelated UID.
            $rows[$row['uid']] = array_replace($rows[$row['uid']] ?? [], $row);
            $rows[$row['uid']]['_state_present'] = true;
        }
        // The link walk (every {$NE.IF.LINK.INTERVAL}) owns negotiated speed and duplex.
        foreach (($link['data'] ?? []) as $row) {
            if (!isset($rows[$row['uid']])) {
                continue;
            }
            foreach (self::LINK_FIELDS as $field) {
                if (($row[$field] ?? null) !== null) {
                    $rows[$row['uid']][$field] = $row[$field];
                }
            }
        }
        foreach ($rows as &$row) {
            foreach (self::LINK_FIELDS as $field) {
                $row[$field] = $row[$field] ?? null;
            }
        }
        unset($row);
        $merged['data'] = array_values($rows);
        if ($inventory !== null) {
            $merged['inventory_observed_at'] = $inventory['observed_at'];
            $observed = is_string($inventory['observed_at']) ? strtotime($inventory['observed_at']) : false;
            $merged['inventory_stale'] = $observed !== false && $observed < $this->now - Limits::INVENTORY_STALE_AFTER;
        }
        return $merged;
    }

    private function quality(?array $envelope, ?array $attempt, string $dataset, ?string $failure): array {
        return ['dataset'=>$dataset] + DatasetQuality::describe($envelope, $attempt, $failure, self::TTL[$dataset],
            $this->now);
    }
}
