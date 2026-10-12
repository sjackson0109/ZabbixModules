<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\EnvelopeValidator;

/**
 * Wi-Fi envelopes at the trust boundary. The envelope itself (size, schema version, common fields, outcome
 * invariants) is checked by Network Explorer's validator; this adds the Wi-Fi row contracts of
 * schemas/wifi-envelope-1.0.schema.json. Any invalid row rejects the whole envelope, so the reader keeps the
 * previous good observation instead of drawing a partly understood one.
 */
final class WifiEnvelopeValidator {
    public const SCHEMAS = ['wifi-1.0'=>['device', 'ap_inventory', 'ap_state', 'radio_inventory', 'radio_state']];
    private const STATUS = ['up', 'down', 'unknown'];
    private const ROLES = ['virtual_controller', 'member', 'controller', 'standalone', 'unknown'];
    private const BANDS = ['2.4', '5', '6'];
    private const WIDTHS = ['20', '40', '80', '160', '80+'];

    private EnvelopeValidator $envelopes;

    public function __construct() {
        $this->envelopes = new EnvelopeValidator();
    }

    public function decode(string $value, string $dataset): array {
        $envelope = $this->envelopes->envelope($value, $dataset, self::SCHEMAS);
        $seen = [];
        foreach ($envelope['data'] as $row) {
            if (!is_array($row)) {
                throw new \InvalidArgumentException('invalid_row');
            }
            $id = $this->row($dataset, $row);
            if ($id !== null) {
                if (isset($seen[$id])) {
                    throw new \InvalidArgumentException('duplicate_identity');
                }
                $seen[$id] = true;
            }
        }
        if ($dataset === 'device' && count($envelope['data']) > 1) {
            throw new \InvalidArgumentException('invalid_device');
        }
        return $envelope;
    }

    public static function validApUid($uid): bool {
        return is_string($uid) && (bool) preg_match('/^ap-[0-9a-f]{24}$/D', $uid);
    }

    public static function validRadioUid($uid): bool {
        return is_string($uid) && (bool) preg_match('/^radio-[0-9a-f]{24}$/D', $uid);
    }

    /** Checks one row and returns its identity within the dataset (null for the single device row). */
    private function row(string $dataset, array $row): ?string {
        switch ($dataset) {
            case 'device':
                self::strings($row, ['hostname'=>256, 'description'=>1024, 'vendor'=>64, 'firmware'=>128]);
                self::enum($row, 'role', self::ROLES, false);
                self::address($row, 'controller_address');
                self::integer($row, 'uptime_s', 0, 2147483648);
                if (isset($row['platform']) && (!is_string($row['platform'])
                        || !preg_match('/^[a-z0-9_]{1,64}$/D', $row['platform']))
                        || isset($row['sys_object_id']) && (!is_string($row['sys_object_id'])
                        || !preg_match('/^[0-9]+(\.[0-9]+)*$/D', $row['sys_object_id']))) {
                    throw new \InvalidArgumentException('invalid_device');
                }
                return null;
            case 'ap_inventory':
                self::apUid($row);
                if (!is_string($row['mac_address'] ?? null)
                        || !preg_match('/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/D', $row['mac_address'])) {
                    throw new \InvalidArgumentException('invalid_ap_identity');
                }
                self::strings($row, ['name'=>256, 'serial'=>128, 'model'=>128, 'firmware'=>128]);
                self::address($row, 'ip_address');
                return $row['ap_uid'];
            case 'ap_state':
                self::apUid($row);
                self::enum($row, 'status', self::STATUS, false);
                self::integer($row, 'uptime_s', 0, 2147483648);
                self::integer($row, 'cpu_percent', 0, 100);
                self::number($row, 'memory_used_percent', 0, 100);
                return $row['ap_uid'];
            case 'radio_inventory':
                self::radioUid($row);
                self::integer($row, 'radio_index', 0, 255, false);
                if (isset($row['bssid']) && (!is_string($row['bssid'])
                        || !preg_match('/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/D', $row['bssid']))) {
                    throw new \InvalidArgumentException('invalid_radio');
                }
                return $row['radio_uid'];
            case 'radio_state':
                self::radioUid($row);
                self::enum($row, 'status', self::STATUS, false);
                self::enum($row, 'band', self::BANDS, true);
                self::enum($row, 'channel_width', self::WIDTHS, true);
                self::integer($row, 'channel', 1, 233);
                self::number($row, 'tx_power_dbm', -10, 40);
                self::number($row, 'noise_floor_dbm', -130, 0);
                self::integer($row, 'utilisation_percent', 0, 100);
                self::integer($row, 'utilisation_window_s', 1, 3600);
                return $row['radio_uid'];
        }
        throw new \InvalidArgumentException('unsupported_schema');
    }

    private static function apUid(array $row): void {
        if (!self::validApUid($row['ap_uid'] ?? null)) {
            throw new \InvalidArgumentException('invalid_ap_identity');
        }
    }

    private static function radioUid(array $row): void {
        if (!self::validRadioUid($row['radio_uid'] ?? null) || !self::validApUid($row['ap_uid'] ?? null)) {
            throw new \InvalidArgumentException('invalid_radio_identity');
        }
    }

    private static function strings(array $row, array $fields): void {
        foreach ($fields as $field => $max) {
            if (isset($row[$field]) && (!is_string($row[$field]) || strlen($row[$field]) > $max)) {
                throw new \InvalidArgumentException('invalid_value');
            }
        }
    }

    private static function enum(array $row, string $field, array $values, bool $nullable): void {
        $value = $row[$field] ?? null;
        if ($value === null ? !$nullable : !in_array($value, $values, true)) {
            throw new \InvalidArgumentException('invalid_value');
        }
    }

    private static function integer(array $row, string $field, int $min, int $max, bool $nullable = true): void {
        $value = $row[$field] ?? null;
        if ($value === null ? !$nullable : !is_int($value) || $value < $min || $value > $max) {
            throw new \InvalidArgumentException('invalid_value');
        }
    }

    private static function number(array $row, string $field, float $min, float $max): void {
        $value = $row[$field] ?? null;
        if ($value !== null && (!is_int($value) && !is_float($value) || $value < $min || $value > $max)) {
            throw new \InvalidArgumentException('invalid_value');
        }
    }

    private static function address(array $row, string $field): void {
        $value = $row[$field] ?? null;
        if ($value !== null && (!is_string($value) || filter_var($value, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) === false)) {
            throw new \InvalidArgumentException('invalid_value');
        }
    }
}
