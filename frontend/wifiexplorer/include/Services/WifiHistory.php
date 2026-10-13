<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Deeper history of one Wi-Fi snapshot item, for the sampled client timeline. Like DataGateway, every result must be
 * restricted to the current user's permissions.
 */
interface WifiHistory {
    /**
     * Values of the item with this exact key on this host between $from and $till, newest first, at most $limit.
     * Reading stops after the value that takes the total size past $maxBytes, so a reader never holds much more
     * than that in memory.
     * @return array<int, array{clock: int, value: string}>
     */
    public function window(string $hostid, string $key, int $from, int $till, int $limit, int $maxBytes): array;
}
