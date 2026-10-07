<?php
declare(strict_types=1);
namespace Modules\NePortPanel;

use Zabbix\Core\CWidget;

class Widget extends CWidget {
    public function getDefaultName(): string {
        return _('Network Explorer: Port panel');
    }
}
