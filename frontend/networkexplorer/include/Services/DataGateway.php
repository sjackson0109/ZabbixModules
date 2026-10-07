<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/** Every gateway result must be restricted to the current user's permissions. */
interface DataGateway {
    public function hosts(array $hostids = []): array;
    public function items(array $hostids): array;
    /** Latest rows PER item, keyed by itemid; never a global history limit. */
    public function history(array $items, int $limit): array;
}
