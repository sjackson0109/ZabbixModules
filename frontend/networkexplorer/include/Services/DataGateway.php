<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Every gateway result must be restricted to the current user's permissions. */
interface DataGateway {
    /**
     * @param array $tags equality conditions [['tag'=>..., 'value'=>...]]; the same tag ORs, different tags AND
     */
    public function hosts(array $hostids = [], array $tags = []): array;
    /** Host IDs and tags of permitted hosts carrying any of these tag names. */
    public function tagged(array $names): array;
    public function items(array $hostids): array;
    /** Latest rows PER item, keyed by itemid; never a global history limit. */
    public function history(array $items, int $limit): array;
}
