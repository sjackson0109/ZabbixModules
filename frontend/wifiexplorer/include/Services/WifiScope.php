<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\NetworkScope;

/**
 * One validated Wi-Fi Explorer request. The site is the `site` host tag of each acquisition owner, the same
 * administrator-controlled tag Network Explorer scopes by; it only narrows what the user may already read.
 */
final class WifiScope {
    public string $site;
    /** The selected AP's opaque ID, or '' for none. A raw MAC address never reaches the address bar. */
    public string $ap;

    private function __construct(string $site, string $ap) {
        $this->site = $site;
        $this->ap = $ap;
    }

    public static function create(string $site = '', string $ap = ''): self {
        if ($site !== '' && !NetworkScope::validTagValue($site)) {
            throw new \InvalidArgumentException('invalid_scope_filter');
        }
        // An invalid selection selects nothing rather than failing the page.
        return new self($site, WifiEnvelopeValidator::validApUid($ap) ? $ap : '');
    }

    public function describe(): array {
        return ['site'=>$this->site];
    }
}
