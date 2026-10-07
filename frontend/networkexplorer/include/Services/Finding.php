<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** The one shape every finding has, with one ID rule, wherever it is raised. */
final class Finding {
    /**
     * @param string      $rule          stable rule name, for example `duplex_mismatch`
     * @param string      $severity      `info` or `warning`
     * @param string|null $hostid        the host the finding is about; null for a scope-wide finding
     * @param string|null $interfaceUid  the interface on that host, when the finding is about one
     * @param string|null $edgeId        the link, when the finding is about one; it is dropped with that link
     */
    public static function create(string $rule, string $severity, ?string $hostid, string $title, string $reason,
            ?string $interfaceUid = null, ?string $edgeId = null): array {
        // The ID is stable across refreshes, so a widget can keep a selected finding while data updates.
        return ['id'=>hash('sha256', implode("\n", [$rule, $hostid ?? '', $interfaceUid ?? '', $edgeId ?? ''])),
            'hostid'=>$hostid, 'interface_uid'=>$interfaceUid, 'edge_id'=>$edgeId, 'severity'=>$severity,
            'rule'=>$rule, 'title'=>$title, 'reason'=>$reason];
    }
}
