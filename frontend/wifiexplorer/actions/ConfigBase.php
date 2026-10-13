<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

require_once dirname(__DIR__).'/include/autoload.php';

use Modules\WifiExplorer\Services\WifiConfig;
use Modules\WifiExplorer\Services\WifiConfigError;
use Modules\WifiExplorer\Services\WifiConfigStore;
use Modules\WifiExplorer\Services\WifiService;

/**
 * Wi-Fi Explorer configuration: floors, AP placement, SSID intent, events and known BSSIDs. Super admins only,
 * because the document is stored in the module's configuration, which only module.update (Super admin) can change.
 */
abstract class ConfigBase extends \CController {
    protected function checkPermissions(): bool {
        return $this->getUserType() == USER_TYPE_SUPER_ADMIN;
    }

    /**
     * Validates a document and records each floor plan's proportions from its Zabbix image.
     * @throws WifiConfigError
     */
    protected static function prepare($document, WifiConfigStore $store): array {
        $config = WifiConfig::normalise($document);
        $problems = [];
        foreach ($config['floors'] as &$floor) {
            if ($floor['imageid'] !== null && $floor['aspect'] === null) {
                $floor['aspect'] = $store->imageAspect($floor['imageid']);
                if ($floor['aspect'] === null) {
                    $problems[] = _s('Floor "%1$s": image %2$s was not found or is not an image.', $floor['floor_id'],
                        $floor['imageid']);
                }
            }
        }
        unset($floor);
        if ($problems) {
            throw new WifiConfigError($problems);
        }
        return $config;
    }

    /** What the editor shows next to the document: the APs and background images it can refer to. */
    protected function editorData(string $text, array $problems = []): array {
        $aps = [];
        try {
            $aps = WifiService::create()->apDirectory();
        }
        catch (\Throwable $error) {
            $aps = [];
        }
        $images = \API::Image()->get(['output'=>['imageid', 'name'], 'filter'=>['imagetype'=>IMAGE_TYPE_BACKGROUND],
            'sortfield'=>'name']);
        return ['text'=>$text, 'problems'=>$problems, 'aps'=>$aps, 'images'=>$images ?: []];
    }

    protected static function pretty(array $config): string {
        return json_encode(WifiConfig::export($config), JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    }
}
