<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

use Modules\WifiExplorer\Services\WifiService;

/**
 * Monitoring -> Wi-Fi Explorer: the site overview, AP inventory, findings and data quality of every permitted
 * Wi-Fi data source. A site narrows it; an AP ID selects one AP's detail.
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
        $data['request'] = ['site'=>(string) $this->getInput('site', ''), 'ap'=>(string) $this->getInput('ap', '')];
        $response = new \CControllerResponseData($data);
        $response->setTitle(_('Wi-Fi Explorer'));
        $this->setResponse($response);
    }
}
