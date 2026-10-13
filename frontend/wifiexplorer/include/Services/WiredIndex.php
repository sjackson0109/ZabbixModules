<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Lookups over Network Explorer's wired model, shared by the path walk and the impact assessment so both resolve
 * hosts, ports and LAG aggregators the same way.
 */
final class WiredIndex {
    /** @return array hostid => host */
    public static function hosts(array $network): array {
        $hosts = [];
        foreach ($network['hosts'] as $host) {
            $hosts[$host['hostid']] = $host;
        }
        return $hosts;
    }

    /** @return array hostid => interface uid => interface */
    public static function interfaces(array $network): array {
        $interfaces = [];
        foreach ($network['interfaces'] as $interface) {
            $interfaces[$interface['hostid']][$interface['uid']] = $interface;
        }
        return $interfaces;
    }

    /** @return array hostid => member uid => aggregator uid; a LAG with no aggregator interface is skipped. */
    public static function aggregators(array $network): array {
        $aggregators = [];
        foreach ($network['lags'] as $lag) {
            if ($lag['interface_uid'] === null) {
                continue;
            }
            foreach ($lag['members'] as $member) {
                $aggregators[$lag['hostid']][$member['uid']] = $lag['interface_uid'];
            }
        }
        return $aggregators;
    }
}
