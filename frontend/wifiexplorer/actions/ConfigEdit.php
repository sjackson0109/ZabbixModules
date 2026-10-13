<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

use Modules\WifiExplorer\Services\WifiConfig;
use Modules\WifiExplorer\Services\WifiConfigStore;

/** Shows the configuration document in an editor, with the AP IDs and floor-plan images it can refer to. */
final class ConfigEdit extends ConfigBase {
    protected function init(): void {
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        return true;
    }

    protected function doAction(): void {
        $problems = [];
        try {
            $text = self::pretty((new WifiConfigStore())->load());
        }
        catch (\RuntimeException $error) {
            $module = \APP::ModuleManager()->getModule(WifiConfigStore::MODULE_ID);
            $stored = $module !== null ? ($module->getConfig()[WifiConfigStore::KEY] ?? null) : null;
            try {
                $stored = WifiConfig::unpack($stored);
            }
            catch (\Modules\WifiExplorer\Services\WifiConfigError $damaged) {
                $stored = null;
            }
            $text = json_encode($stored ?? WifiConfig::empty(), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
            $problems[] = _('The stored configuration does not validate; correct it and save.');
        }
        $response = new \CControllerResponseData($this->editorData($text, $problems));
        $response->setTitle(_('Wi-Fi Explorer configuration'));
        $this->setResponse($response);
    }
}
