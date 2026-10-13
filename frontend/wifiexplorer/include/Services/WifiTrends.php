<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Hourly trends of the templates' numeric capacity items, for the long-term capacity views. Like DataGateway, every
 * result must be restricted to the current user's permissions.
 */
interface WifiTrends {
    /**
     * Hourly trend rows of the numeric items with exactly these keys on these hosts, between $from and $till, as
     * compact lists [hostid, key, clock, avg, max]. At most $limit rows; a reader returns one more to show that the
     * limit was reached.
     * @return array<int, array{0: string, 1: string, 2: int, 3: float, 4: float}>
     */
    public function trends(array $hostids, array $keys, int $from, int $till, int $limit): array;
}
