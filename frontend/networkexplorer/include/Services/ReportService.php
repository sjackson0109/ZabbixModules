<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

final class ReportService {
    public const REPORTS = ['inventory','peers','addressing','degradation','vlans','stp','quality','findings'];

    public function rows(array $network, string $report): array {
        if (!in_array($report, self::REPORTS, true)) {
            throw new \InvalidArgumentException('invalid_report');
        }
        switch ($report) {
            case 'inventory':
                return array_map(static fn($row) => array_intersect_key($row,
                    array_flip(['hostid','host','name','domain','vendor','model','firmware','management_addresses'])),
                    $network['hosts']);
            case 'peers':
                return $network['edges'];
            case 'addressing':
                return array_map(static fn($row) => ['hostid'=>$row['hostid'], 'name'=>$row['name'],
                    'domain'=>$row['domain'], 'addresses'=>$row['management_addresses'], 'assessment'=>$row['addressing']],
                    $network['hosts']);
            case 'degradation':
                return array_values(array_filter($network['interfaces'],
                    static fn($row) => $row['speed_degraded'] || $row['state'] === 'down'
                        || $row['state'] === 'duplex_observation'));
            case 'vlans':
                return array_values(array_map(static fn($row) => ['hostid'=>$row['hostid'], 'interface'=>$row['name'] ?? null,
                    'interface_uid'=>$row['uid']] + $row['vlan'], array_filter($network['interfaces'],
                    static fn($row) => ($row['vlan'] ?? null) !== null)));
            case 'stp':
                $result = [];
                foreach ($network['interfaces'] as $row) {
                    foreach ($row['stp'] ?? [] as $port) {
                        $result[] = ['hostid'=>$row['hostid'], 'interface'=>$row['name'] ?? null,
                            'interface_uid'=>$row['uid']] + $port;
                    }
                }
                return $result;
            case 'quality':
                return $network['quality'];
            default:
                return $network['findings'];
        }
    }

    public function csv(array $rows): string {
        $columns = [];
        foreach ($rows as $row) {
            foreach (array_keys($row) as $key) {
                $columns[$key] = true;
            }
        }
        $columns = array_keys($columns);
        $stream = fopen('php://temp', 'w+');
        fputcsv($stream, $columns, ',', '"', '');
        foreach ($rows as $row) {
            $values = [];
            foreach ($columns as $column) {
                $value = $row[$column] ?? '';
                if (is_array($value)) {
                    $value = json_encode($value, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
                }
                elseif (is_bool($value)) {
                    $value = $value ? 'true' : 'false';
                }
                $value = (string) $value;
                // Prefix every spreadsheet execution/control character, including
                // formulas hidden behind spaces. Keep RFC CSV quoting intact.
                if (preg_match('/^[\s\x00-\x20]*[=+@-]/u', $value)
                        || preg_match('/^[\t\r\n]/', $value)) {
                    $value = "'".$value;
                }
                $values[] = $value;
            }
            fputcsv($stream, $values, ',', '"', '');
        }
        rewind($stream);
        $result = stream_get_contents($stream);
        fclose($stream);
        return $result;
    }

    /** CSV records retain the same observation context as the JSON report. */
    public function contextualRows(array $network, string $report): array {
        $rows = $this->rows($network, $report);
        $quality = [];
        foreach ($network['quality'] as $entry) {
            $quality[$entry['hostid']][] = $entry;
        }
        foreach ($rows as &$row) {
            $hostids = [];
            foreach (['hostid','source','target'] as $field) {
                if (isset($row[$field])) {
                    $hostids[(string) $row[$field]] = true;
                }
            }
            $coverage = [];
            foreach (array_keys($hostids) as $id) {
                foreach ($quality[$id] ?? [] as $entry) {
                    $coverage[] = array_intersect_key($entry, array_flip(['hostid','dataset','status',
                        'capability','freshness','observed_at','age_seconds']));
                }
            }
            $row['report_generated_at'] = $network['generated_at'];
            $row['report_scope'] = $network['scope'];
            $row['observation_coverage'] = $coverage;
        }
        unset($row);
        return $rows;
    }
}
