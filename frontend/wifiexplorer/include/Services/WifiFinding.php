<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\Finding;

/**
 * A Wi-Fi finding: Network Explorer's finding shape and stable ID rule, plus the affected Wi-Fi object and the
 * evidence behind it, so every finding can say what was observed, when, and how fresh it is.
 */
final class WifiFinding {
    /**
     * @param string      $objectType `site`, `owner`, `ap` or `radio`
     * @param string|null $objectId   the opaque ID of that object (ap_uid, radio_uid), or null for a host or site
     * @param array       $evidence   [['dataset'=>..., 'observed_at'=>..., 'fact'=>...], ...]
     */
    public static function create(string $rule, string $severity, ?string $hostid, string $objectType,
            ?string $objectId, string $title, string $reason, array $evidence, string $freshness,
            ?string $remediation = null, string $confidence = 'observed'): array {
        $finding = Finding::create($rule, $severity, $hostid, $title, $reason,
            $objectId !== null ? $objectType.':'.$objectId : null);
        unset($finding['interface_uid'], $finding['edge_id']);
        $observed = array_values(array_filter(array_column($evidence, 'observed_at')));
        sort($observed);
        return $finding + ['object_type'=>$objectType, 'object_id'=>$objectId, 'evidence'=>$evidence,
            // Wi-Fi Explorer keeps no finding history yet: last observed is the newest evidence behind it.
            'last_observed'=>$observed ? end($observed) : null, 'freshness'=>$freshness,
            'confidence'=>$confidence, 'remediation'=>$remediation];
    }

    private function __construct() {
    }
}
