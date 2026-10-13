<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\NetworkScope;

/**
 * One validated Wi-Fi Explorer request. The site is the `site` host tag of each acquisition owner, the same
 * administrator-controlled tag Network Explorer scopes by; it only narrows what the user may already read.
 *
 * Everything else in the address bar is an opaque ID or a fixed choice (requirements section 25): never a MAC
 * address, an SSID secret or a client identifier. An invalid ID selects nothing rather than failing the page.
 */
final class WifiScope {
    public const VIEWS = ['overview', 'floors', 'rf', 'ssids', 'paths', 'impact', 'events', 'clients'];

    public string $site = '';
    /** The selected AP's opaque ID, or '' for none. */
    public string $ap = '';
    public string $view = 'overview';
    public string $floor = '';
    public string $overlay = 'status';
    public string $band = '';
    public string $ssid = '';
    public string $client = '';
    /** A wired element to assess the impact of: a Network Explorer host ID and, optionally, its interface UID. */
    public string $failHost = '';
    public string $failInterface = '';
    public string $event = '';
    /** Free-text search over AP and client fields the viewer can already see. */
    public string $query = '';

    private function __construct() {
    }

    public static function create(string $site = '', string $ap = '', array $more = []): self {
        if ($site !== '' && !NetworkScope::validTagValue($site)) {
            throw new \InvalidArgumentException('invalid_scope_filter');
        }
        $scope = new self();
        $scope->site = $site;
        $scope->ap = WifiEnvelopeValidator::validApUid($ap) ? $ap : '';
        $value = static fn(string $key): string => is_string($more[$key] ?? null) ? $more[$key] : '';
        $scope->view = in_array($value('view'), self::VIEWS, true) ? $value('view') : 'overview';
        $scope->floor = preg_match('/^[a-z0-9][a-z0-9_-]{0,63}$/D', $value('floor')) ? $value('floor') : '';
        $scope->overlay = in_array($value('overlay'), FloorService::OVERLAYS, true) ? $value('overlay') : 'status';
        $scope->band = in_array($value('band'), ['2.4', '5', '6'], true) ? $value('band') : '';
        $scope->ssid = WifiEnvelopeValidator::validSsidUid($value('ssid')) ? $value('ssid') : '';
        $scope->client = WifiEnvelopeValidator::validClientUid($value('client')) ? $value('client') : '';
        $scope->failHost = preg_match('/^[1-9][0-9]{0,19}$/D', $value('fail_host')) ? $value('fail_host') : '';
        $scope->failInterface = $scope->failHost !== '' && preg_match('/^[A-Za-z0-9_.:-]{1,128}$/D', $value('fail_if'))
            ? $value('fail_if') : '';
        $scope->event = preg_match('/^[a-z0-9][a-z0-9_-]{0,63}$/D', $value('event')) ? $value('event') : '';
        $query = trim($value('q'));
        $scope->query = strlen($query) <= 64 && !preg_match('/[\x00-\x1f\x7f]/', $query) ? $query : '';
        return $scope;
    }

    public function describe(): array {
        return ['site'=>$this->site, 'view'=>$this->view];
    }

    /**
     * The views that correlate with Network Explorer's wired model. The overview needs it too, so that its findings
     * include uplink and VLAN path findings and do not change when an AP is selected.
     */
    public function needsWired(): bool {
        return in_array($this->view, ['overview', 'ssids', 'paths', 'impact', 'events', 'clients'], true) || $this->ap !== '';
    }
}
