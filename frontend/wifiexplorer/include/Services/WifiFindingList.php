<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * The order and grouping of the Overview's findings table. Warnings come first; within a severity, problems with
 * APs and radios come before SSID, RF, path and event findings, and data-collection problems come last. One host's
 * failed and stale datasets share one row (`group` lists them), so a struggling data source cannot push the device
 * problems it hides off the page. The findings themselves, their IDs and counts are unchanged.
 */
final class WifiFindingList {
    private const COLLECTION = ['wifi_dataset_failed', 'wifi_dataset_stale'];

    public static function overview(array $findings): array {
        $rows = [];
        $collection = [];
        foreach ($findings as $finding) {
            if (in_array($finding['rule'], self::COLLECTION, true) && $finding['hostid'] !== null) {
                if (!isset($collection[$finding['hostid']])) {
                    $collection[$finding['hostid']] = count($rows);
                    $rows[] = ['group'=>[]] + $finding;
                }
                $rows[$collection[$finding['hostid']]]['group'][] = $finding;
                continue;
            }
            $rows[] = $finding;
        }
        foreach ($rows as &$row) {
            // A host with a single failed or stale dataset keeps its ordinary row.
            if (isset($row['group']) && count($row['group']) === 1) {
                $row = $row['group'][0];
            }
        }
        unset($row);
        usort($rows, static fn($a, $b) => self::rank($a) <=> self::rank($b));
        return $rows;
    }

    private static function rank(array $finding): int {
        $kind = in_array($finding['object_type'], ['ap', 'radio'], true) ? 0
            : (in_array($finding['rule'], self::COLLECTION, true) || $finding['object_type'] === 'owner' ? 2 : 1);
        return ($finding['severity'] === 'warning' ? 0 : 3) + $kind;
    }

    private function __construct() {
    }
}
