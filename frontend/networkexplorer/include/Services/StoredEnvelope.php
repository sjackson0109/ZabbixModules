<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * The native templates store envelopes without the times Zabbix already records: no attempted_at, observed_at or
 * generation_id, and "timing":"zabbix" to say so. A value is stored only when it changes (and every
 * {$NE.HEARTBEAT}), so the stored JSON stays identical while nothing changes. Row times the device reports relative
 * to its own uptime are stored as absolute times rounded to the minute (boot_at, topology_changed_at).
 *
 * rehydrate() restores the canonical envelope before it is validated, from Zabbix's value timestamps:
 *   - attempted_at and observed_at from the stored row's clock, or for a complete success from the time of the last
 *     complete observation (the clock of ne.collection.success[...] / we.collection.success[...]), since every
 *     observation since the row was stored was identical;
 *   - uptime_s from boot_at, time_since_topology_change_s from topology_changed_at, and an LLDP row's observed_at
 *     from the envelope's.
 * Any other value (canonical envelopes from the collector, the lab or an earlier template) is returned unchanged.
 */
final class StoredEnvelope {
    public static function rehydrate(string $value, int $clock, ?int $observed = null): string {
        if (strpos($value, '"timing":"zabbix"') === false) {
            return $value;
        }
        try {
            $envelope = json_decode($value, true, 32, JSON_THROW_ON_ERROR);
        }
        catch (\JsonException $e) {
            return $value;
        }
        if (!is_array($envelope) || ($envelope['timing'] ?? null) !== 'zabbix') {
            return $value;
        }
        unset($envelope['timing']);
        $status = $envelope['status'] ?? null;
        $seen = $status === 'ok' && $observed !== null ? max($clock, $observed) : $clock;
        $envelope['attempted_at'] = self::iso($seen);
        $envelope['observed_at'] = in_array($status, ['failed', 'unsupported'], true) ? null : self::iso($seen);
        $envelope['generation_id'] = substr((string) ($envelope['dataset'] ?? 'dataset'), 0, 64).'-zabbix-'.$clock;
        if (is_array($envelope['data'] ?? null)) {
            foreach ($envelope['data'] as &$row) {
                if (!is_array($row)) {
                    continue;
                }
                if (array_key_exists('boot_at', $row)) {
                    $row['uptime_s'] = self::since($row['boot_at'], $seen);
                    unset($row['boot_at']);
                }
                if (array_key_exists('topology_changed_at', $row)) {
                    $row['time_since_topology_change_s'] = self::since($row['topology_changed_at'], $seen);
                    unset($row['topology_changed_at']);
                }
                if (($envelope['dataset'] ?? null) === 'lldp' && !array_key_exists('observed_at', $row)) {
                    $row['observed_at'] = $envelope['observed_at'];
                }
            }
            unset($row);
        }
        return json_encode($envelope, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_PRESERVE_ZERO_FRACTION);
    }

    private static function iso(int $clock): string {
        return gmdate('Y-m-d\TH:i:s\Z', $clock);
    }

    /** Whole seconds from an absolute time to $clock; null when unknown or unreadable, never negative. */
    private static function since($time, int $clock): ?int {
        if (!is_string($time) || ($epoch = strtotime($time)) === false) {
            return null;
        }
        return max(0, $clock - $epoch);
    }
}
