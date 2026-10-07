<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Structural contract validation at the trust boundary; bounded before decode. */
final class EnvelopeValidator {
    public const MAX_BYTES = 2097152;
    public const MAX_ROWS = 20000;

    public function decode(string $value, string $dataset): array {
        if (strlen($value) > self::MAX_BYTES) {
            throw new \InvalidArgumentException('payload_too_large');
        }
        try {
            $envelope = json_decode($value, true, 32, JSON_THROW_ON_ERROR);
        }
        catch (\JsonException $e) {
            throw new \InvalidArgumentException('invalid_json');
        }
        if (!is_array($envelope) || ($envelope['schema_version'] ?? null) !== '1.0') {
            throw new \InvalidArgumentException('unsupported_schema');
        }
        if (($envelope['dataset'] ?? null) !== $dataset
                || !in_array($envelope['status'] ?? null, ['ok','partial','failed','unsupported'], true)
                || !is_bool($envelope['complete'] ?? null)
                || !is_string($envelope['generation_id'] ?? null)
                || $envelope['generation_id'] === ''
                || strlen($envelope['generation_id']) > 128
                || !is_array($envelope['source'] ?? null)
                || !in_array($envelope['source']['method'] ?? null, ['native_snmp','python_snmp','fixture','agent'], true)
                || !is_string($envelope['source']['adapter'] ?? null)
                || $envelope['source']['adapter'] === '' || strlen($envelope['source']['adapter']) > 128
                || !is_string($envelope['source']['version'] ?? null)
                || $envelope['source']['version'] === '' || strlen($envelope['source']['version']) > 32
                || !is_array($envelope['capability'] ?? null)
                || !in_array($envelope['capability']['state'] ?? null,
                    ['supported','partial','unsupported','unknown'], true)
                || !is_array($envelope['errors'] ?? null)
                || !array_key_exists('observed_at', $envelope)
                || !is_array($envelope['data'] ?? null)
                || count($envelope['data']) > self::MAX_ROWS
                || array_keys($envelope['data']) !== range(0, count($envelope['data']) - 1)
                    && $envelope['data'] !== []) {
            throw new \InvalidArgumentException('invalid_envelope');
        }
        // Mirror the authoritative envelope schema's outcome invariants before
        // accepting any observation rows. A failure cannot carry fresh data.
        $status = $envelope['status'];
        if ($status === 'ok' && (!$envelope['complete'] || $envelope['errors'] !== []
                || $envelope['capability']['state'] !== 'supported')) {
            throw new \InvalidArgumentException('invalid_success_outcome');
        }
        if ($status !== 'ok' && $envelope['complete']) {
            throw new \InvalidArgumentException('invalid_incomplete_outcome');
        }
        if (in_array($status, ['failed','unsupported'], true)
                && ($envelope['observed_at'] !== null || $envelope['data'] !== [])) {
            throw new \InvalidArgumentException('invalid_failure_outcome');
        }
        if ($status === 'partial' && $envelope['capability']['state'] !== 'partial'
                || $status === 'unsupported' && $envelope['capability']['state'] !== 'unsupported') {
            throw new \InvalidArgumentException('invalid_capability_outcome');
        }
        foreach (['attempted_at','observed_at'] as $field) {
            $timestamp = $envelope[$field] ?? null;
            if ($field === 'observed_at' && $timestamp === null
                    && in_array($envelope['status'], ['failed','unsupported'], true)) {
                continue;
            }
            if (!is_string($timestamp) || !preg_match(
                    '/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/D', $timestamp)
                    || strtotime($timestamp) === false) {
                throw new \InvalidArgumentException('invalid_timestamp');
            }
        }
        $seenUids = [];
        foreach ($envelope['data'] as $row) {
            if (!is_array($row)) {
                throw new \InvalidArgumentException('invalid_row');
            }
            if ($dataset === 'interfaces') {
                if (!self::validUid($row['uid'] ?? null)
                        || !isset($row['if_index']) || !is_int($row['if_index']) || $row['if_index'] < 1) {
                    throw new \InvalidArgumentException('invalid_interface_identity');
                }
                if (isset($seenUids[$row['uid']])) {
                    throw new \InvalidArgumentException('duplicate_interface_identity');
                }
                $seenUids[$row['uid']] = true;
                foreach (['speed_bps','expected_speed_bps','mtu'] as $field) {
                    if (isset($row[$field]) && (!is_int($row[$field]) || $row[$field] < 0)) {
                        throw new \InvalidArgumentException('invalid_interface_value');
                    }
                }
                foreach (['name','description','alias','mac_address'] as $field) {
                    self::nullableString($row, $field);
                }
                if (isset($row['physical']) && !is_bool($row['physical'])
                        || isset($row['type']) && (!is_int($row['type']) || $row['type'] < 0)) {
                    throw new \InvalidArgumentException('invalid_interface_value');
                }
                foreach (['member','slot','port'] as $field) {
                    if (isset($row[$field]) && !is_string($row[$field]) && !is_int($row[$field])) {
                        throw new \InvalidArgumentException('invalid_interface_value');
                    }
                }
                foreach (['admin_status'=>['up','down','testing'],
                        'oper_status'=>['up','down','testing','unknown','dormant','not_present','lower_layer_down'],
                        'duplex'=>['half','full']] as $field => $allowed) {
                    if (isset($row[$field]) && !in_array($row[$field], $allowed, true)) {
                        throw new \InvalidArgumentException('invalid_interface_value');
                    }
                }
            }
            if ($dataset === 'device') {
                foreach (['hostname','vendor','model','firmware'] as $field) {
                    self::nullableString($row, $field);
                }
                if (isset($row['chassis_ids'])) {
                    if (!is_array($row['chassis_ids']) || count($row['chassis_ids']) > 128) {
                        throw new \InvalidArgumentException('invalid_device_identity');
                    }
                    foreach ($row['chassis_ids'] as $id) {
                        self::identifier($id);
                    }
                }
                self::addresses($row['management_addresses'] ?? []);
            }
            if ($dataset === 'lldp') {
                foreach (['local_port_id','remote_chassis_id','remote_port_id'] as $field) {
                    self::identifier($row[$field] ?? null);
                }
                if (isset($row['local_interface_uid']) && !self::validUid($row['local_interface_uid'])) {
                    throw new \InvalidArgumentException('invalid_interface_identity');
                }
                foreach (['remote_system_name','remote_port_description'] as $field) {
                    self::nullableString($row, $field);
                }
                self::addresses($row['remote_management_addresses'] ?? []);
            }
            if ($dataset === 'lag' && (!self::validUid($row['uid'] ?? null)
                    || !is_array($row['member_interface_uids'] ?? null))) {
                throw new \InvalidArgumentException('invalid_lag');
            }
            if ($dataset === 'lag') {
                self::nullableString($row, 'name');
                foreach ($row['member_interface_uids'] as $uid) {
                    if (!self::validUid($uid)) {
                        throw new \InvalidArgumentException('invalid_lag');
                    }
                }
            }
        }
        return $envelope;
    }

    public static function validUid($uid): bool {
        return is_string($uid) && (bool) preg_match('/^[A-Za-z0-9_.:-]{1,128}$/D', $uid);
    }

    private static function nullableString(array $row, string $field): void {
        if (isset($row[$field]) && (!is_string($row[$field]) || strlen($row[$field]) > 4096)) {
            throw new \InvalidArgumentException('invalid_field_type');
        }
    }

    private static function identifier($id): void {
        if (!is_array($id) || !array_key_exists('subtype', $id) || !is_string($id['value'] ?? null)
                || strlen($id['value']) > 4096 || $id['subtype'] !== null
                    && (!is_int($id['subtype']) || $id['subtype'] < 1 || $id['subtype'] > 7)) {
            throw new \InvalidArgumentException('invalid_lldp_identity');
        }
    }

    private static function addresses($addresses): void {
        if (!is_array($addresses) || count($addresses) > 128) {
            throw new \InvalidArgumentException('invalid_address_list');
        }
        foreach ($addresses as $address) {
            if (!is_string($address) || strlen($address) > 255) {
                throw new \InvalidArgumentException('invalid_address_list');
            }
        }
    }
}
