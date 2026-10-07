<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer;

use Zabbix\Core\CModule;

final class Module extends CModule {
    public function init(): void {
        require_once __DIR__.'/include/autoload.php';
        // Zabbix authenticates the user before it initialises modules, so the menu shows the entry only to users
        // whose role can open the page.
        if (\CWebUser::checkAccess(\CRoleHelper::UI_MONITORING_HOSTS)) {
            \APP::Component()->get('menu.main')->findOrAdd(_('Monitoring'))->getSubMenu()->add(
                (new \CMenuItem(_('Network Explorer')))->setAction('networkexplorer.view')
            );
        }
    }
}
