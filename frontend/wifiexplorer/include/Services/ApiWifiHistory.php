<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/** WifiHistory through the logged-in frontend's local API, which applies the user's permissions to items and history. */
final class ApiWifiHistory implements WifiHistory {
    public function window(string $hostid, string $key, int $from, int $till, int $limit): array {
        $items = \API::Item()->get(['output'=>['itemid', 'value_type'], 'hostids'=>[$hostid], 'filter'=>['key_'=>$key],
            'monitored'=>true, 'limit'=>1]);
        if (!$items || (int) $items[0]['value_type'] !== ITEM_VALUE_TYPE_TEXT) {
            return [];
        }
        $rows = \API::History()->get(['output'=>['clock', 'value'], 'history'=>ITEM_VALUE_TYPE_TEXT,
            'itemids'=>[$items[0]['itemid']], 'time_from'=>$from, 'time_till'=>$till, 'sortfield'=>'clock',
            'sortorder'=>ZBX_SORT_DOWN, 'limit'=>$limit]);
        return array_map(static fn($row) => ['clock'=>(int) $row['clock'], 'value'=>(string) $row['value']], $rows ?: []);
    }
}
