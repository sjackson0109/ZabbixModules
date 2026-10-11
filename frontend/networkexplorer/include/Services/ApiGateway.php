<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Uses the logged-in frontend's local API; no token or privileged connection. */
final class ApiGateway implements DataGateway {
    private array $authorisedItems = [];
    private array $authorisedHosts = [];

    public function hosts(array $hostids = [], array $tags = []): array {
        $options = ['output'=>['hostid','host','name'], 'monitored_hosts'=>true,
            'selectTags'=>['tag','value'], 'selectInterfaces'=>['ip','dns','useip','type','available'],
            'selectMacros'=>['macro','value','type'], 'sortfield'=>'hostid', 'limit'=>Limits::CANDIDATE_HOSTS + 1];
        if ($hostids) {
            $options['hostids'] = $hostids;
        }
        if ($tags) {
            $options['evaltype'] = TAG_EVAL_TYPE_AND_OR;
            $options['tags'] = self::tagFilter($tags);
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

    public function hostids(array $tags, int $limit): array {
        $rows = \API::Host()->get(['output'=>['hostid'], 'monitored_hosts'=>true, 'evaltype'=>TAG_EVAL_TYPE_AND_OR,
            'tags'=>self::tagFilter($tags), 'sortfield'=>'hostid', 'limit'=>$limit]);
        return array_map(static fn($row) => (string) $row['hostid'], $rows);
    }

    public function networkHostids(array $keys, int $limit, ?array $hostids = null): array {
        if ($hostids === []) {
            return [];
        }
        $options = ['output'=>['hostid'], 'monitored'=>true, 'filter'=>['key_'=>array_values($keys)],
            'sortfield'=>'itemid', 'limit'=>$limit];
        if ($hostids !== null) {
            $options['hostids'] = array_values($hostids);
        }
        $rows = \API::Item()->get($options);
        $ids = array_values(array_unique(array_map(static fn($row) => (string) $row['hostid'], $rows)));
        usort($ids, static fn($a, $b) => strnatcmp($a, $b));
        return $ids;
    }

    public function tagged(array $names): array {
        $rows = \API::Host()->get(['output'=>['hostid'], 'monitored_hosts'=>true, 'selectTags'=>['tag','value'],
            'evaltype'=>TAG_EVAL_TYPE_OR, 'tags'=>array_map(static fn($name) => ['tag'=>(string) $name,
                'operator'=>TAG_OPERATOR_EXISTS], $names), 'limit'=>Limits::OPTION_HOSTS + 1]);
        // Only the requested tags leave the gateway.
        return array_map(static fn($row) => ['hostid'=>(string) $row['hostid'], 'tags'=>array_values(array_filter(
            $row['tags'] ?? [], static fn($tag) => in_array($tag['tag'] ?? null, $names, true)))], $rows);
    }

    public function items(array $hostids, array $keys = []): array {
        $hostids = array_values(array_filter($hostids,
            fn($id): bool => isset($this->authorisedHosts[(string) $id])));
        if (!$hostids) {
            return [];
        }
        $options = ['output'=>['itemid','hostid','key_','value_type','state','status'], 'hostids'=>$hostids,
            'limit'=>Limits::ITEMS + 1];
        $options += $keys
            ? ['filter'=>['key_'=>array_values($keys)]]
            : ['search'=>['key_'=>'ne.'], 'startSearch'=>true];
        $rows = \API::Item()->get($options);
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

    /** Exact tag equality conditions; the same tag ORs, different tags AND (with TAG_EVAL_TYPE_AND_OR). */
    private static function tagFilter(array $tags): array {
        return array_map(static fn($tag) => ['tag'=>(string) $tag['tag'], 'value'=>(string) $tag['value'],
            'operator'=>TAG_OPERATOR_EQUAL], $tags);
    }
}
