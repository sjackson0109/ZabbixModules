<?php
declare(strict_types=1);
namespace Modules\NeTopology;

use Zabbix\Core\CWidget;

class Widget extends CWidget {
    public function getDefaultName(): string {
        return _('Network Explorer: Topology');
    }
}
