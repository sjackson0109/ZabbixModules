<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer;

use Zabbix\Core\CModule;

final class Module extends CModule {
    public function init(): void {
        require_once __DIR__.'/include/autoload.php';
        \APP::Component()->get('menu.main')->findOrAdd(_('Monitoring'))->getSubMenu()->add(
            (new \CMenuItem(_('Network Explorer')))->setAction('networkexplorer.view')
        );
    }
}
