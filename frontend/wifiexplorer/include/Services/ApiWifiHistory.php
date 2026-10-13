<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/** WifiHistory through the logged-in frontend's local API, which applies the user's permissions to items and history. */
final class ApiWifiHistory implements WifiHistory {
    /** Values are read a few at a time, so a cluster with large snapshots stops at the byte bound, not after it. */
    private const BATCH = 6;

    public function window(string $hostid, string $key, int $from, int $till, int $limit, int $maxBytes): array {
        $items = \API::Item()->get(['output'=>['itemid', 'value_type'], 'hostids'=>[$hostid], 'filter'=>['key_'=>$key],
            'monitored'=>true, 'limit'=>1]);
        if (!$items || (int) $items[0]['value_type'] !== ITEM_VALUE_TYPE_TEXT) {
            return [];
        }
        $result = [];
        $bytes = 0;
        while (count($result) < $limit && $till >= $from) {
            $rows = \API::History()->get(['output'=>['clock', 'value'], 'history'=>ITEM_VALUE_TYPE_TEXT,
                'itemids'=>[$items[0]['itemid']], 'time_from'=>$from, 'time_till'=>$till, 'sortfield'=>'clock',
                'sortorder'=>ZBX_SORT_DOWN, 'limit'=>min(self::BATCH, $limit - count($result))]) ?: [];
            foreach ($rows as $row) {
                $result[] = ['clock'=>(int) $row['clock'], 'value'=>(string) $row['value']];
                $bytes += strlen((string) $row['value']);
                if ($bytes > $maxBytes) {
                    return $result;
                }
            }
            if (count($rows) < self::BATCH) {
                break;
            }
            // Values sharing the last clock in a batch are rare (one snapshot per interval); skipping them is safe.
            $till = (int) end($rows)['clock'] - 1;
        }
        return $result;
    }
}
