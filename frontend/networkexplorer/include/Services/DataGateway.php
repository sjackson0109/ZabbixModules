<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Every gateway result must be restricted to the current user's permissions. */
interface DataGateway {
    /**
     * @param array $tags equality conditions [['tag'=>..., 'value'=>...]]; the same tag ORs, different tags AND
     */
    public function hosts(array $hostids = [], array $tags = []): array;
    /**
     * IDs only of permitted hosts matching these tag conditions (as for hosts()), in host order, at most $limit.
     * @return string[]
     */
    public function hostids(array $tags, int $limit): array;
    /**
     * IDs of permitted hosts that carry a Network Explorer item with one of these exact keys, at most $limit rows
     * read; with $hostids, only among those hosts. Hosts without such an item (servers, other devices) are never
     * part of the answer.
     * @return string[]
     */
    public function networkHostids(array $keys, int $limit, ?array $hostids = null): array;
    /** Host IDs and tags of permitted hosts carrying any of these tag names. */
    public function tagged(array $names): array;
    /** Network Explorer items of these hosts; with $keys, only items with exactly those keys. */
    public function items(array $hostids, array $keys = []): array;
    /** Latest rows PER item, keyed by itemid; never a global history limit. */
    public function history(array $items, int $limit): array;
}
