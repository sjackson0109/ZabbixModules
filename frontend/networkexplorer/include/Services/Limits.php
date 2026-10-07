<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Read budgets that keep one page request bounded. Every reader enforces these, never the browser. */
final class Limits {
    /** Hosts in one network view; one more is requested to detect truncation. */
    public const HOSTS = 300;
    public const INTERFACES = 30000;
    /** Network Explorer items read per request; one more is requested to detect overflow. */
    public const ITEMS = 50000;
    public const HISTORY_ITEMS = 3000;
    public const HISTORY_BYTES = 64 * 1024 * 1024;
    /** Oldest history value considered when reading the latest snapshot. */
    public const HISTORY_PERIOD = 7 * 86400;
    /** Inventory older than this is reported as stale. */
    public const INVENTORY_STALE_AFTER = 2 * 3600;

    private function __construct() {
    }
}
