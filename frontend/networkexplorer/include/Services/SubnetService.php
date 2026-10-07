<?php

declare(strict_types=1);

namespace Modules\NetworkExplorer\Services;

/** IPv4/IPv6 scope annotations; outside-scope addresses never hide permitted graph peers. */
final class SubnetService {

    public function validate(string $cidr): bool {
        return $this->parse($cidr) !== null;
    }

    public function contains(string $address, string $cidr): bool {
        $network = $this->parse($cidr);
        $packed = @inet_pton(trim($address));
        if ($network === null || $packed === false || strlen($packed) !== strlen($network['packed'])) {
            return false;
        }
        $fullBytes = intdiv($network['prefix'], 8);
        if (substr($packed, 0, $fullBytes) !== substr($network['packed'], 0, $fullBytes)) {
            return false;
        }
        $bits = $network['prefix'] % 8;
        if ($bits === 0) {
            return true;
        }
        $mask = (0xff << (8 - $bits)) & 0xff;
        return (ord($packed[$fullBytes]) & $mask) === (ord($network['packed'][$fullBytes]) & $mask);
    }

    public function annotate(array $addresses, array $cidrs): array {
        $valid = [];
        $invalid = [];
        foreach ($cidrs as $cidr) {
            if (is_string($cidr) && $this->validate($cidr)) {
                $valid[] = trim($cidr);
            }
            else {
                $invalid[] = is_scalar($cidr) ? (string) $cidr : '';
            }
        }
        $rows = [];
        $states = [];
        foreach ($addresses as $address) {
            if (is_array($address)) {
                $address = $address['address'] ?? $address['value'] ?? $address['ip'] ?? '';
            }
            $address = is_string($address) ? trim($address) : '';
            $matches = [];
            if ($address !== '' && @inet_pton($address) !== false) {
                foreach ($valid as $cidr) {
                    if ($this->contains($address, $cidr)) {
                        $matches[] = $cidr;
                    }
                }
                $state = !$valid ? 'unknown' : ($matches ? 'inside' : 'outside');
            }
            else {
                $state = 'unknown';
            }
            $states[$state] = true;
            $rows[] = ['address' => $address, 'state' => $state, 'matched_cidrs' => $matches];
        }
        $status = !$states || isset($states['unknown']) ? 'unknown'
            : (count($states) > 1 ? 'mixed' : (isset($states['inside']) ? 'within' : 'outside'));
        return ['status' => $status, 'addresses' => $rows, 'cidrs' => array_values(array_unique($valid)),
            'invalid_cidrs' => array_values(array_unique($invalid))];
    }

    private function parse(string $cidr): ?array {
        $parts = explode('/', trim($cidr));
        if (count($parts) !== 2 || !preg_match('/^[0-9]{1,3}$/D', $parts[1])) {
            return null;
        }
        $packed = @inet_pton($parts[0]);
        $prefix = (int) $parts[1];
        if ($packed === false || $prefix > strlen($packed) * 8) {
            return null;
        }
        return ['packed' => $packed, 'prefix' => $prefix];
    }
}
