<?php
declare(strict_types=1);
namespace Modules\WifiExplorer;

use Zabbix\Core\CModule;

final class Module extends CModule {
    public function init(): void {
        require_once __DIR__.'/include/autoload.php';
        // Same gate as Network Explorer: only users whose role can open Monitoring -> Hosts see the entry.
        if (\CWebUser::checkAccess(\CRoleHelper::UI_MONITORING_HOSTS)) {
            \APP::Component()->get('menu.main')->findOrAdd(_('Monitoring'))->getSubMenu()->add(
                (new \CMenuItem(_('Wi-Fi Explorer')))->setAction('wifiexplorer.view')
            );
        }
    }
}
