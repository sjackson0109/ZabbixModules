<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Structural contract validation at the trust boundary; bounded before decode. */
final class EnvelopeValidator {
    public const MAX_BYTES = 2097152;
    public const MAX_ROWS = 20000;
    /** The schema's bound on LAG member lists. */
    private const MAX_LAG_MEMBERS = 4096;
    /** 1.1 adds port_capability, vlan and stp; existing dataset rows are unchanged. */
    public const SCHEMAS = ['1.0'=>['device','interfaces','lldp','lag'],
        '1.1'=>['device','interfaces','lldp','lag','port_capability','vlan','stp']];

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
        $version = is_array($envelope) ? ($envelope['schema_version'] ?? null) : null;
        if (!is_string($version) || !in_array($dataset, self::SCHEMAS[$version] ?? [], true)) {
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
        // 1.1 warnings report rows that were dropped or left with unknown fields; the observation still stands.
        $warnings = $envelope['warnings'] ?? [];
        if (array_key_exists('warnings', $envelope) && $version === '1.0'
                || !is_array($warnings) || count($warnings) > 256
                || array_filter($warnings, static fn($warning) => !is_array($warning)
                    || !is_string($warning['code'] ?? null) || !preg_match('/^[a-z0-9_]{1,64}$/D', $warning['code']))) {
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
                    if (isset($row[$field]) && !is_int($row[$field])) {
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
                // 1.1 peer attributes feed expected speed, duplex and native VLAN checks.
                self::speeds($row['remote_advertised_speeds_bps'] ?? null, 'invalid_lldp_peer');
                $enabled = $row['capabilities']['enabled'] ?? [];
                if (!in_array($row['remote_duplex'] ?? null, [null,'half','full','unknown'], true)
                        || ($row['remote_pvid'] ?? null) !== null && !self::vlanId($row['remote_pvid'])
                        || !is_array($enabled) || count($enabled) > 16
                        || array_filter($enabled, static fn($cap) => !is_string($cap) || strlen($cap) > 32)) {
                    throw new \InvalidArgumentException('invalid_lldp_peer');
                }
            }
            if ($dataset === 'lag' && (!self::validUid($row['uid'] ?? null)
                    || !is_array($row['member_interface_uids'] ?? null))) {
                throw new \InvalidArgumentException('invalid_lag');
            }
            if ($dataset === 'lag') {
                self::nullableString($row, 'name');
                self::lag($row);
            }
            if ($dataset === 'port_capability') {
                self::interfaceRef($row, 'uid');
                foreach (['supported_speeds_bps','advertised_speeds_bps','partner_advertised_speeds_bps'] as $field) {
                    self::speeds($row[$field] ?? null);
                }
                if (isset($row['oper_speed_bps']) && (!is_int($row['oper_speed_bps']) || $row['oper_speed_bps'] < 0)
                        || isset($row['autoneg_enabled']) && !is_bool($row['autoneg_enabled'])
                        || isset($row['oper_duplex']) && !in_array($row['oper_duplex'], ['half','full'], true)
                        || isset($row['media']) && !in_array($row['media'], ['copper','sfp','sfp_plus'], true)) {
                    throw new \InvalidArgumentException('invalid_port_capability');
                }
            }
            if ($dataset === 'vlan') {
                $kind = $row['kind'] ?? null;
                if ($kind === 'vlan') {
                    if (!self::vlanId($row['vlan_id'] ?? null)) {
                        throw new \InvalidArgumentException('invalid_vlan');
                    }
                    self::nullableString($row, 'name');
                }
                elseif ($kind === 'port') {
                    self::interfaceRef($row, 'interface_uid');
                    if (!in_array($row['mode'] ?? null, ['access','trunk','hybrid','unknown'], true)
                            || isset($row['pvid']) && !self::vlanId($row['pvid'])) {
                        throw new \InvalidArgumentException('invalid_vlan');
                    }
                    foreach (['tagged','untagged','forbidden','current_egress','current_untagged'] as $field) {
                        if (isset($row[$field]) && (!is_string($row[$field])
                                || !preg_match('/^(?:\d{1,4}(?:-\d{1,4})?(?:,\d{1,4}(?:-\d{1,4})?)*)?$/D', $row[$field]))) {
                            throw new \InvalidArgumentException('invalid_vlan');
                        }
                    }
                }
                else {
                    throw new \InvalidArgumentException('invalid_vlan');
                }
            }
            if ($dataset === 'stp') {
                $kind = $row['kind'] ?? null;
                if (!in_array($kind, ['bridge','port'], true)
                        || !is_int($row['instance'] ?? null) || $row['instance'] < 0 || $row['instance'] > 4094) {
                    throw new \InvalidArgumentException('invalid_stp');
                }
                if ($kind === 'port') {
                    self::interfaceRef($row, 'interface_uid');
                    if (isset($row['role']) && !in_array($row['role'],
                            ['root','designated','alternate','backup','disabled','master','unknown'], true)
                            || isset($row['state']) && !in_array($row['state'],
                            ['disabled','blocking','listening','learning','forwarding','broken','discarding','unknown'], true)) {
                        throw new \InvalidArgumentException('invalid_stp');
                    }
                }
                foreach (['bridge_id','root_bridge_id','designated_bridge'] as $field) {
                    if (isset($row[$field]) && (!is_string($row[$field]) || !preg_match('/^[0-9a-f]{16}$/D', $row[$field]))) {
                        throw new \InvalidArgumentException('invalid_stp');
                    }
                }
                if (isset($row['root_port_uid']) && !self::validUid($row['root_port_uid'])) {
                    throw new \InvalidArgumentException('invalid_stp');
                }
                if (isset($row['protocol'])
                        && !in_array($row['protocol'], ['stp','rstp','mstp','pvst','rapid_pvst','unknown'], true)) {
                    throw new \InvalidArgumentException('invalid_stp');
                }
                foreach (['cost','root_cost','priority','topology_changes','time_since_topology_change_s'] as $field) {
                    if (isset($row[$field]) && !is_int($row[$field])) {
                        throw new \InvalidArgumentException('invalid_stp');
                    }
                }
                self::nullableString($row, 'vlans');
            }
        }
        return $envelope;
    }

    public static function validUid($uid): bool {
        return is_string($uid) && (bool) preg_match('/^[A-Za-z0-9_.:-]{1,128}$/D', $uid);
    }

    /** LAG membership and per-member LACP state, as TopologyService reads them. */
    private static function lag(array $row): void {
        $members = $row['members'] ?? [];
        if (count($row['member_interface_uids']) > self::MAX_LAG_MEMBERS
                || array_filter($row['member_interface_uids'], static fn($uid) => !self::validUid($uid))
                || !in_array($row['mode'] ?? null, [null, 'lacp', 'static', 'pagp', 'unknown'], true)
                || !is_array($members) || count($members) > self::MAX_LAG_MEMBERS) {
            throw new \InvalidArgumentException('invalid_lag');
        }
        foreach ($members as $member) {
            if (!is_array($member) || !self::validUid($member['uid'] ?? null)) {
                throw new \InvalidArgumentException('invalid_lag');
            }
            foreach (['selected', 'collecting', 'distributing', 'lacp_active'] as $flag) {
                if (($member[$flag] ?? null) !== null && !is_bool($member[$flag])) {
                    throw new \InvalidArgumentException('invalid_lag');
                }
            }
            $port = $member['partner_port'] ?? null;
            if ($port !== null && (!is_int($port) || $port < 0)) {
                throw new \InvalidArgumentException('invalid_lag');
            }
        }
    }

    private static function nullableString(array $row, string $field): void {
        if (isset($row[$field]) && (!is_string($row[$field]) || strlen($row[$field]) > 4096)) {
            throw new \InvalidArgumentException('invalid_field_type');
        }
    }

    private static function interfaceRef(array $row, string $field): void {
        // Rows whose interface could not be resolved carry null rather than a guess.
        if (($row[$field] ?? null) !== null && !self::validUid($row[$field])) {
            throw new \InvalidArgumentException('invalid_interface_identity');
        }
    }

    private static function vlanId($id): bool {
        return is_int($id) && $id >= 1 && $id <= 4094;
    }

    private static function speeds($speeds, string $code = 'invalid_port_capability'): void {
        if ($speeds === null) {
            return;
        }
        if (!is_array($speeds) || count($speeds) > 64) {
            throw new \InvalidArgumentException($code);
        }
        foreach ($speeds as $speed) {
            if (!is_int($speed) || $speed <= 0) {
                throw new \InvalidArgumentException($code);
            }
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
