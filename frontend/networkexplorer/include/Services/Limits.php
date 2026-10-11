<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Read budgets that keep one page request bounded. Every reader enforces these, never the browser. */
final class Limits {
    /**
     * Switches drawn and fully read in one network view. A scope with more is not drawn at all: the response says
     * how many it holds and asks for a narrower scope, so no switch is ever silently left out.
     */
    public const DISPLAY_HOSTS = 300;
    /**
     * Network Explorer hosts examined to find the scope and the peers its LLDP observations may name: every
     * Network Explorer host in the scope's domains, up to this many. Hosts without a Network Explorer item never
     * count. Only their device and LLDP snapshots are read unless they are drawn. One more is requested to detect
     * truncation, which is reported, never silent.
     */
    public const CANDIDATE_HOSTS = 1000;
    /**
     * Permitted host IDs listed for one site or domain filter before Network Explorer membership is checked (IDs
     * only, so a far larger safety bound). A filter matching more is not drawn: its devices cannot all be known.
     */
    public const SCOPE_HOSTS = 20000;
    public const INTERFACES = 30000;
    /** Hosts whose tags populate the site and domain selectors, and the values listed for each. */
    public const OPTION_HOSTS = 10000;
    public const OPTION_VALUES = 500;
    /** Network Explorer items read per request; one more is requested to detect overflow. */
    public const ITEMS = 50000;
    /** Snapshot items read per pass (drawn hosts carry up to 16 each; identity candidates two). */
    public const HISTORY_ITEMS = 6000;
    public const HISTORY_BYTES = 64 * 1024 * 1024;
    /** Oldest history value considered when reading the latest snapshot. */
    public const HISTORY_PERIOD = 7 * 86400;
    /** Inventory older than this is reported as stale. */
    public const INVENTORY_STALE_AFTER = 2 * 3600;

    private function __construct() {
    }
}
