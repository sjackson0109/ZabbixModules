<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

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
                $sites = $this->service()->siteOptions();
            }
            catch (\Throwable $error) {
                $sites = [];
            }
        }
        $data['sites'] = $sites;
        $data['request'] = $this->request();
        // A malformed site or AP has already been reported by wifi(); the view falls back to the overview.
        try {
            $data['scope_view'] = $this->scope()->view;
        }
        catch (\InvalidArgumentException $error) {
            $data['scope_view'] = 'overview';
        }
        $data['can_configure'] = \CWebUser::getType() == USER_TYPE_SUPER_ADMIN;
        $response = new \CControllerResponseData($data);
        $response->setTitle(_('Wi-Fi Explorer'));
        $this->setResponse($response);
    }
}
