<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * Decides the speed an interface is expected to run at, and why.
 * Order: explicit dataset policy, per-port host macro, highest speed both ends advertise.
 */
final class SpeedIntent {
    private const MACRO = '/^\{\$NE\.IF\.EXPECTED_SPEED:(?:"((?:[^"\\\\]|\\\\.)*)"|\s*([^"}\s][^}]*))\}$/D';

    /** Per-port overrides keyed by interface name, from {$NE.IF.EXPECTED_SPEED:"<ifName>"} host macros. */
    public static function overrides(array $macros): array {
        $result = [];
        foreach ($macros as $macro) {
            $value = trim((string) ($macro['value'] ?? ''));
            // The trigger reads the same macro, where Zabbix suffixes are binary; only plain bit/s is unambiguous.
            if (!preg_match(self::MACRO, (string) ($macro['macro'] ?? ''), $match)
                    || !preg_match('/^[0-9]{1,15}$/D', $value) || (int) $value === 0) {
                continue;
            }
            $name = ($match[1] ?? '') !== '' ? stripcslashes($match[1]) : rtrim($match[2] ?? '');
            $result[$name] = (int) $value;
        }
        return $result;
    }

    /**
     * Effective expected speed, per the precedence in docs/design/02-canonical-schema.md.
     * @return array{0: ?int, 1: string, 2: ?string} bit/s, source label, and the evidence behind it
     */
    public static function derive(array $interface, ?array $capability, ?array $lldp, array $overrides): array {
        $explicit = $interface['expected_speed_bps'] ?? null;
        if (is_numeric($explicit) && $explicit > 0) {
            return [(int) $explicit, 'policy', 'dataset'];
        }
        $name = $interface['name'] ?? null;
        if (is_string($name) && isset($overrides[$name])) {
            return [$overrides[$name], 'policy', 'port_macro'];
        }
        $local = self::speeds($capability['advertised_speeds_bps'] ?? null)
            ?: self::speeds($capability['supported_speeds_bps'] ?? null);
        // Without both ends' abilities, a port that legitimately serves a slower device looks degraded.
        foreach ([[$capability['partner_advertised_speeds_bps'] ?? null, 'partner_mau'],
                [$lldp['remote_advertised_speeds_bps'] ?? null, 'lldp_peer']] as [$peer, $basis]) {
            $common = array_intersect($local, self::speeds($peer));
            if ($common) {
                return [max($common), 'negotiable', $basis];
            }
        }
        // A bridge on the far end is an uplink, which should run at the port's best speed.
        if ($local && in_array('bridge', $lldp['capabilities']['enabled'] ?? [], true)) {
            return [max($local), 'uplink_capability', 'lldp_bridge_peer'];
        }
        return [null, 'unknown', null];
    }

    private static function speeds($list): array {
        return is_array($list) ? array_values(array_filter($list, static fn($v) => is_int($v) && $v > 0)) : [];
    }
}
