<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * WifiTrends through the logged-in frontend's local API, which applies the user's permissions to items and trends.
 * Trends are read one item at a time and kept as compact rows, so a year of hourly values stays small in memory.
 */
final class ApiWifiTrends implements WifiTrends {
    public function trends(array $hostids, array $keys, int $from, int $till, int $limit): array {
        if (!$hostids || !$keys) {
            return [];
        }
        $items = \API::Item()->get(['output'=>['itemid', 'hostid', 'key_'], 'hostids'=>$hostids,
            'filter'=>['key_'=>$keys, 'value_type'=>[ITEM_VALUE_TYPE_FLOAT, ITEM_VALUE_TYPE_UINT64]], 'monitored'=>true]);
        $result = [];
        foreach ($items ?: [] as $item) {
            $hostid = (string) $item['hostid'];
            $key = (string) $item['key_'];
            $rows = \API::Trend()->get(['output'=>['clock', 'value_avg', 'value_max'], 'itemids'=>[$item['itemid']],
                'time_from'=>$from, 'time_till'=>$till, 'limit'=>$limit + 1 - count($result)]);
            foreach ($rows ?: [] as $row) {
                $result[] = [$hostid, $key, (int) $row['clock'], (float) $row['value_avg'], (float) $row['value_max']];
            }
            if (count($result) > $limit) {
                break;
            }
        }
        return $result;
    }
}
