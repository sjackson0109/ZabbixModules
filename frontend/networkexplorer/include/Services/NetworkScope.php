<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * One validated network view request: optional seed hosts, site and domain filters, and management CIDRs.
 *
 * Site and domain only narrow the hosts the current user may already read; they never grant access. Both come from
 * administrator-controlled host tags (`site` and `ne.domain`), never from names, addresses or LLDP.
 */
final class NetworkScope {
    public const SITE_TAG = 'site';
    public const DOMAIN_TAG = 'ne.domain';
    public const MAX_TAG_VALUE = 128;
    private const MAX_CIDRS = 32;
    private const MAX_CIDR_TEXT = 2048;

    /** @var string[] */
    public array $seedHostids;
    public string $site;
    public string $domain;
    /** @var string[] */
    public array $managementCidrs;
    /** True when the response should list the scope's candidate devices (for a seed selector). */
    public bool $listCandidates;

    private function __construct(array $seedHostids, string $site, string $domain, array $managementCidrs,
            bool $listCandidates) {
        $this->seedHostids = $seedHostids;
        $this->site = $site;
        $this->domain = $domain;
        $this->managementCidrs = $managementCidrs;
        $this->listCandidates = $listCandidates;
    }

    public static function create(array $seedHostids = [], string $managementCidr = '', string $site = '',
            string $domain = '', bool $listCandidates = false): self {
        $seedHostids = array_values(array_unique(array_map('strval', $seedHostids)));
        foreach ($seedHostids as $id) {
            if (!preg_match('/^[1-9][0-9]*$/D', $id)) {
                throw new \InvalidArgumentException('invalid_hostid');
            }
        }
        if (count($seedHostids) > Limits::HOSTS) {
            throw new \InvalidArgumentException('host_budget_exceeded');
        }
        foreach ([$site, $domain] as $value) {
            if (!self::validTagValue($value) && $value !== '') {
                throw new \InvalidArgumentException('invalid_scope_filter');
            }
        }
        return new self($seedHostids, $site, $domain, self::cidrs($managementCidr), $listCandidates);
    }

    public static function validTagValue(string $value): bool {
        return $value !== '' && strlen($value) <= self::MAX_TAG_VALUE && preg_match('//u', $value) === 1
            && !preg_match('/[\x00-\x1f\x7f]/', $value);
    }

    /** The single value a host carries for a tag, or '' when it has none or several. */
    public static function tagValue(array $tags, string $name): string {
        $values = [];
        foreach ($tags as $tag) {
            if (($tag['tag'] ?? null) === $name && is_string($tag['value'] ?? null) && self::validTagValue($tag['value'])) {
                $values[$tag['value']] = true;
            }
        }
        return count($values) === 1 ? (string) array_key_first($values) : '';
    }

    public function seeded(): bool {
        return $this->seedHostids !== [];
    }

    public function filtered(): bool {
        return $this->site !== '' || $this->domain !== '';
    }

    /** Whole permitted fleet: no seed and no filter. */
    public function fleet(): bool {
        return !$this->seeded() && !$this->filtered();
    }

    /** Host tag conditions for the filters; equal tags OR together, different tags AND together. */
    public function tagConditions(): array {
        $conditions = [];
        if ($this->site !== '') {
            $conditions[] = ['tag'=>self::SITE_TAG, 'value'=>$this->site];
        }
        if ($this->domain !== '') {
            $conditions[] = ['tag'=>self::DOMAIN_TAG, 'value'=>$this->domain];
        }
        return $conditions;
    }

    /** Whether a described host (with `site` and `domain`) passes the filters. */
    public function matches(array $host): bool {
        return ($this->site === '' || $host['site'] === $this->site)
            && ($this->domain === '' || $host['domain'] === $this->domain);
    }

    public function describe(): array {
        return ['seed_hostids'=>$this->seedHostids, 'site'=>$this->site, 'domain'=>$this->domain,
            'management_cidrs'=>$this->managementCidrs];
    }

    /** @return string[] */
    private static function cidrs(string $text): array {
        if (strlen($text) > self::MAX_CIDR_TEXT) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $cidrs = trim($text) === '' ? [] : preg_split('/[\s,]+/', trim($text));
        if (count($cidrs) > self::MAX_CIDRS) {
            throw new \InvalidArgumentException('invalid_management_cidr');
        }
        $subnet = new SubnetService();
        foreach ($cidrs as $cidr) {
            if (!$subnet->validate($cidr)) {
                throw new \InvalidArgumentException('invalid_management_cidr');
            }
        }
        return $cidrs;
    }
}
