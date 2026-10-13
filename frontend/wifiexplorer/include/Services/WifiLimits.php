<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/** Read budgets for one Wi-Fi Explorer request, enforced on the server. Network Explorer's Limits cover the rest. */
final class WifiLimits {
    /** Acquisition owners (controllers, virtual controllers, standalone APs) read in one request. */
    public const OWNER_HOSTS = 500;
    /** APs shown in one view. A scope with more is not drawn: the page asks for a site instead of truncating. */
    public const DISPLAY_APS = 5000;
    /** Radio utilisation (observed, per the source's sampling window) at or above which a radio is highly utilised. */
    public const HIGH_UTILISATION = 70;
    /** Clients listed in one view; a search narrows the rest. */
    public const DISPLAY_CLIENTS = 500;
    /** The sampled client timeline: how far back, how many snapshots, and how many bytes of them at most. */
    public const CLIENT_HISTORY_S = 21600;
    public const CLIENT_HISTORY_SAMPLES = 72;
    public const CLIENT_HISTORY_BYTES = 16777216;
    /**
     * Hourly capacity trend rows read for one view: a year of the seven year-view keys is about 61,000 rows per
     * cluster, so a site of four clusters fits; a larger scope is asked to narrow.
     */
    public const TREND_ROWS = 250000;

    private function __construct() {
    }
}
