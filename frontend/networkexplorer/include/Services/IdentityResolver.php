<?php

declare(strict_types=1);

namespace Modules\NetworkExplorer\Services;

/** Resolves LLDP identity only against the permission-filtered input host set. */
final class IdentityResolver {

    private array $hosts = [];
    private array $interfaces = [];
    private array $chassis = [];
    private array $addresses = [];
    private array $names = [];

    public function __construct(array $hosts, array $datasets) {
        foreach ($hosts as $key => $host) {
            if (!is_array($host)) {
                continue;
            }
            $hostid = (string) ($host['hostid'] ?? $key);
            $domain = trim((string) ($host['domain'] ?? $host['network_domain'] ?? ''));
            $this->hosts[$hostid] = ['domain' => $domain];
            $this->interfaces[$hostid] = [];
            $duplicateUids = [];
            foreach (self::rows($datasets[$hostid]['interfaces'] ?? []) as $interface) {
                if (is_array($interface) && isset($interface['uid'])) {
                    $uid = (string) $interface['uid'];
                    if (isset($this->interfaces[$hostid][$uid]) || isset($duplicateUids[$uid])) {
                        unset($this->interfaces[$hostid][$uid]);
                        $duplicateUids[$uid] = true;
                    }
                    else {
                        $this->interfaces[$hostid][$uid] = $interface;
                    }
                }
            }
            // Missing routing-domain policy never grants a cross-device match.
            if ($domain === '') {
                continue;
            }
            foreach (['name', 'host'] as $field) {
                $this->add($this->names, $domain, self::name((string) ($host[$field] ?? '')), $hostid);
            }
            // Configured SNMP endpoints are authorised host metadata with explicit domain policy.
            foreach (($host['management_addresses'] ?? []) as $address) {
                $this->add($this->addresses, $domain, self::addressKey($address), $hostid);
            }
            foreach (self::rows($datasets[$hostid]['device'] ?? []) as $device) {
                if (!is_array($device)) {
                    continue;
                }
                $ids = $device['chassis_ids'] ?? [];
                if (isset($device['chassis_id']) && is_array($device['chassis_id'])) {
                    $ids[] = $device['chassis_id'];
                }
                foreach ($ids as $id) {
                    if (is_array($id)) {
                        $this->add($this->chassis, $domain, self::chassisKey($id), $hostid);
                    }
                }
                foreach (($device['management_addresses'] ?? []) as $address) {
                    $this->add($this->addresses, $domain, self::addressKey($address), $hostid);
                }
                foreach (['system_name', 'sys_name', 'hostname', 'name'] as $field) {
                    $this->add($this->names, $domain, self::name((string) ($device[$field] ?? '')), $hostid);
                }
            }
        }
    }

    /** No unresolved result contains remote identifiers, addresses, or device names. */
    public function resolve(array $observation, string $sourceHostid): array {
        $domain = $this->hosts[$sourceHostid]['domain'] ?? '';
        if ($domain === '') {
            return $this->unresolved('unresolved', [], ['domain_missing']);
        }
        $chassisKey = self::chassisKey($observation['remote_chassis_id'] ?? []);
        $chassis = $this->candidates($this->chassis, $domain, $chassisKey);
        $addresses = [];
        foreach (($observation['remote_management_addresses'] ?? []) as $address) {
            $addresses = array_values(array_unique(array_merge($addresses,
                $this->candidates($this->addresses, $domain, self::addressKey($address))
            )));
        }
        $evidence = [];
        if ($chassis) {
            $evidence[] = 'chassis_identity';
        }
        if ($addresses) {
            $evidence[] = 'management_address';
        }
        $candidates = $chassis ?: $addresses;
        if ($chassis && $addresses) {
            $common = array_values(array_intersect($chassis, $addresses));
            if (!$common || (count($chassis) === 1 && count($addresses) > 1)) {
                return $this->unresolved('ambiguous', array_unique(array_merge($chassis, $addresses)),
                    array_merge($evidence, ['conflicting_identity']));
            }
            $candidates = $common;
        }
        if (!$candidates) {
            return $this->unresolved('unresolved', [], ['no_corroborated_identity']);
        }
        $name = self::name((string) ($observation['remote_system_name'] ?? ''));
        $nameCandidates = $this->candidates($this->names, $domain, $name);
        // A name can disambiguate corroborated evidence; a name alone cannot identify a host.
        if (count($nameCandidates) === 1 && in_array($nameCandidates[0], $candidates, true)) {
            $candidates = $nameCandidates;
            $evidence[] = 'corroborated_system_name';
        }
        if (count($candidates) !== 1) {
            return $this->unresolved('ambiguous', $candidates, $evidence);
        }
        $hostid = (string) $candidates[0];
        $port = is_array($observation['remote_port_id'] ?? null) ? $observation['remote_port_id'] : [];
        $matches = $this->interfaceCandidates($hostid, $port);
        if (isset($observation['remote_if_index']) && is_int($observation['remote_if_index'])
                && $observation['remote_if_index'] > 0) {
            // An adapter may explicitly establish this join; the raw LLDP local ID cannot.
            $explicit = array_values(array_filter($this->interfaces[$hostid] ?? [],
                static fn(array $interface): bool => isset($interface['if_index'])
                    && (int) $interface['if_index'] === $observation['remote_if_index']));
            if (!$matches || (count($explicit) === 1 && count($matches) === 1
                    && $explicit[0]['uid'] === $matches[0]['uid'])) {
                $matches = $explicit;
                $evidence[] = 'adapter_if_index';
            }
            elseif ($explicit !== $matches) {
                $matches = array_values(array_merge($matches, $explicit));
                $evidence[] = 'conflicting_port_identity';
            }
        }
        $result = [
            'status' => 'resolved',
            'hostid' => $hostid,
            'interface_uid' => count($matches) === 1 ? (string) $matches[0]['uid'] : null,
            'candidate_count' => 1,
            'interface_candidate_count' => count($matches),
            'evidence' => $evidence
        ];
        if (count($matches) > 1) {
            $result['evidence'][] = 'ambiguous_remote_port';
        }
        elseif (!$matches) {
            $result['evidence'][] = 'unmapped_remote_port';
        }
        return $result;
    }

    public function resolveInterface(string $hostid, array $portId, ?string $preferredUid = null): ?array {
        if ($preferredUid !== null && isset($this->interfaces[$hostid][$preferredUid])) {
            return $this->interfaces[$hostid][$preferredUid];
        }
        $matches = $this->interfaceCandidates($hostid, $portId);
        return count($matches) === 1 ? $matches[0] : null;
    }

    public function interfaceByUid(string $hostid, string $uid): ?array {
        return $this->interfaces[$hostid][$uid] ?? null;
    }

    /** Accepts either a canonical envelope or its already extracted rows. */
    public static function rows(array $dataset): array {
        return isset($dataset['data']) && is_array($dataset['data']) ? $dataset['data'] : $dataset;
    }

    private function interfaceCandidates(string $hostid, array $portId): array {
        $subtype = (int) ($portId['subtype'] ?? 0);
        $value = trim((string) ($portId['value'] ?? ''));
        if ($value === '') {
            return [];
        }
        $matches = [];
        foreach ($this->interfaces[$hostid] ?? [] as $interface) {
            $match = false;
            if ($subtype === 3) {
                $mac = self::mac($value);
                $match = $mac !== '' && $mac === self::mac((string) ($interface['mac'] ?? $interface['mac_address'] ?? ''));
            }
            elseif ($subtype === 1) {
                $match = (string) ($interface['alias'] ?? '') === $value;
            }
            elseif ($subtype === 5) {
                $match = (string) ($interface['name'] ?? '') === $value;
            }
            elseif ($subtype === 7) {
                // Locally assigned IDs require an explicit adapter mapping, including numeric IDs.
                $match = in_array($value, array_map('strval', $interface['lldp_local_ids'] ?? []), true);
            }
            elseif ($subtype === 2) {
                $match = (string) ($interface['port_component'] ?? '') === $value;
            }
            if ($match) {
                $matches[] = $interface;
            }
        }
        return $matches;
    }

    private static function chassisKey(array $id): string {
        $subtype = (int) ($id['subtype'] ?? 0);
        $value = trim((string) ($id['value'] ?? ''));
        if ($subtype < 1 || $subtype > 7 || $value === '') {
            return '';
        }
        if ($subtype === 4) {
            $value = self::mac($value);
        }
        elseif ($subtype === 5) {
            $value = self::addressKey($value);
        }
        // Opaque chassis/local IDs remain case-sensitive: case folding can merge distinct devices.
        return $value === '' ? '' : $subtype . ':' . $value;
    }

    private static function mac(string $value): string {
        $value = strtolower(preg_replace('/[:.\-\s]/', '', $value) ?? '');
        return preg_match('/^[0-9a-f]{12}$/D', $value) ? $value : '';
    }

    private static function addressKey($address): string {
        if (is_array($address)) {
            $address = $address['address'] ?? $address['value'] ?? $address['ip'] ?? '';
        }
        if (!is_string($address)) {
            return '';
        }
        $packed = @inet_pton(trim($address));
        return $packed === false ? '' : bin2hex($packed);
    }

    private static function name(string $value): string {
        return strtolower(rtrim(trim($value), '.'));
    }

    private function add(array &$index, string $domain, string $key, string $hostid): void {
        if ($key !== '') {
            $index[$domain][$key][$hostid] = true;
        }
    }

    private function candidates(array $index, string $domain, string $key): array {
        return array_map('strval', array_keys($index[$domain][$key] ?? []));
    }

    private function unresolved(string $status, array $candidates, array $evidence): array {
        return ['status' => $status, 'candidate_count' => count($candidates), 'evidence' => $evidence];
    }
}
