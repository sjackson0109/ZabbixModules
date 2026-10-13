<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

use Modules\WifiExplorer\Services\WifiService;

/**
 * Monitoring -> Wi-Fi Explorer: the site overview, floor plans, RF neighbours, SSIDs, service paths, impact,
 * event readiness and clients of every permitted Wi-Fi data source. A site narrows it; opaque IDs select an AP,
 * SSID or client.
 */
final class Explorer extends Base {
    protected function doAction(): void {
        $data = $this->wifi();
        $sites = [];
        if (self::networkExplorerInstalled()) {
            try {
                $sites = WifiService::create()->siteOptions();
            }
            catch (\Throwable $error) {
                $sites = [];
            }
        }
        $data['sites'] = $sites;
        $data['request'] = $this->request();
        $data['scope_view'] = $this->scope()->view;
        $data['can_configure'] = \CWebUser::getType() == USER_TYPE_SUPER_ADMIN;
        $response = new \CControllerResponseData($data);
        $response->setTitle(_('Wi-Fi Explorer'));
        $this->setResponse($response);
    }
}
