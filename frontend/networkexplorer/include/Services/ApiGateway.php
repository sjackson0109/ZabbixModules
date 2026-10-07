<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Uses the logged-in frontend's local API; no token or privileged connection. */
final class ApiGateway implements DataGateway {
    private array $authorisedItems = [];
    private array $authorisedHosts = [];

    public function hosts(array $hostids = []): array {
        $options = ['output'=>['hostid','host','name'], 'monitored_hosts'=>true,
            'selectTags'=>['tag','value'], 'selectInterfaces'=>['ip','dns','useip','type','available'],
            'selectMacros'=>['macro','value','type'], 'sortfield'=>'hostid', 'limit'=>Limits::HOSTS + 1];
        if ($hostids) {
            $options['hostids'] = $hostids;
        }
        $rows = \API::Host()->get($options);
        foreach ($rows as &$row) {
            $this->authorisedHosts[(string) $row['hostid']] = true;
            // Only plain-text per-port speed intent leaves the gateway; other host macros may hold secrets.
            $row['macros'] = array_values(array_filter($row['macros'] ?? [], static fn($macro): bool =>
                (int) ($macro['type'] ?? -1) === ZBX_MACRO_TYPE_TEXT && strpos((string) $macro['macro'], '{$NE.IF.EXPECTED_SPEED:') === 0));
        }
        unset($row);
        return $rows;
    }

    public function items(array $hostids): array {
        $hostids = array_values(array_filter($hostids,
            fn($id): bool => isset($this->authorisedHosts[(string) $id])));
        if (!$hostids) {
            return [];
        }
        $rows = \API::Item()->get(['output'=>['itemid','hostid','key_','value_type','state','status'],
            'hostids'=>$hostids, 'search'=>['key_'=>'ne.'], 'startSearch'=>true,
            'limit'=>Limits::ITEMS + 1]);
        foreach ($rows as $row) {
            $this->authorisedItems[(string) $row['itemid']] = $row;
        }
        return $rows;
    }

    public function history(array $items, int $limit): array {
        $safe = [];
        foreach ($items as $item) {
            $id = (string) $item['itemid'];
            if (isset($this->authorisedItems[$id])) {
                // Value type comes from authorised metadata, not caller input.
                $safe[] = $this->authorisedItems[$id];
            }
        }
        $limit = max(1, min(3, $limit));
        $result = [];
        foreach (array_chunk($safe, 50) as $batch) {
            // Supported frontend manager, after explicit host/item authorisation.
            // Its SQL/Elasticsearch adapter returns $limit rows for EACH item.
            $result += \Manager::History()->getLastValues($batch, $limit, Limits::HISTORY_PERIOD);
        }
        return $result;
    }
}
