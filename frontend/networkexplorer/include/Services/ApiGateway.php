<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Uses the logged-in frontend's local API; no token or privileged connection. */
final class ApiGateway implements DataGateway {
    private array $authorisedItems = [];
    private array $authorisedHosts = [];
    public array $metrics = ['host_calls'=>0, 'item_calls'=>0, 'history_batches'=>0,
        'history_items'=>0, 'dashboard_calls'=>0];

    public function hosts(array $hostids = []): array {
        $options = ['output'=>['hostid','host','name'], 'monitored_hosts'=>true,
            'selectTags'=>['tag','value'], 'selectInterfaces'=>['ip','dns','useip','type'],
            'sortfield'=>'hostid', 'limit'=>301];
        if ($hostids) {
            $options['hostids'] = $hostids;
        }
        ++$this->metrics['host_calls'];
        $rows = \API::Host()->get($options);
        foreach ($rows as $row) {
            $this->authorisedHosts[(string) $row['hostid']] = true;
        }
        return $rows;
    }

    public function items(array $hostids): array {
        $hostids = array_values(array_filter($hostids,
            fn($id): bool => isset($this->authorisedHosts[(string) $id])));
        if (!$hostids) {
            return [];
        }
        ++$this->metrics['item_calls'];
        $rows = \API::Item()->get(['output'=>['itemid','hostid','key_','value_type','state','status'],
            'hostids'=>$hostids, 'search'=>['key_'=>'ne.'], 'startSearch'=>true,
            'limit'=>50001]);
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
            ++$this->metrics['history_batches'];
            $this->metrics['history_items'] += count($batch);
            // Supported frontend manager, after explicit host/item authorisation.
            // Its SQL/Elasticsearch adapter returns $limit rows for EACH item.
            $result += \Manager::History()->getLastValues($batch, $limit, 604800);
        }
        return $result;
    }

    public function dashboards(array $hostids): array {
        $result = [];
        // HostDashboard API accepts multiple host IDs but rows do not carry hostid.
        // Query only displayed hosts and cap one page request to 300 hosts.
        foreach (array_slice($hostids, 0, 300) as $hostid) {
            if (!isset($this->authorisedHosts[(string) $hostid])) {
                continue;
            }
            ++$this->metrics['dashboard_calls'];
            $rows = \API::HostDashboard()->get(['output'=>['dashboardid','name'],
                'hostids'=>[(string) $hostid], 'sortfield'=>'name', 'limit'=>1]);
            $result[(string) $hostid] = $rows[0]['dashboardid'] ?? null;
        }
        return $result;
    }
}
