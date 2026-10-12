<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * Where the Wi-Fi configuration document is kept: the module's own configuration in the Zabbix database. Reading
 * needs no privilege beyond the page; writing goes through module.update, which only a Super admin may call.
 */
class WifiConfigStore {
    public const MODULE_ID = 'wifiexplorer';
    public const KEY = 'wifi';

    public function load(): array {
        $module = \APP::ModuleManager()->getModule(self::MODULE_ID);
        $document = $module !== null ? ($module->getConfig()[self::KEY] ?? null) : null;
        if ($document === null) {
            return WifiConfig::empty();
        }
        try {
            return WifiConfig::normalise($document);
        }
        catch (WifiConfigError $error) {
            // A stored document that no longer validates is not half-applied.
            throw new \RuntimeException('configuration_invalid');
        }
    }

    public function save(array $config): void {
        if (\CWebUser::getType() != USER_TYPE_SUPER_ADMIN) {
            throw new \RuntimeException('configuration_forbidden');
        }
        $module = \APP::ModuleManager()->getModule(self::MODULE_ID);
        if ($module === null) {
            throw new \RuntimeException('configuration_unavailable');
        }
        $stored = $module->getConfig();
        $stored[self::KEY] = $config;
        $result = \API::Module()->update([['moduleid'=>$module->getModuleId(), 'config'=>$stored]]);
        if ($result === false) {
            throw new \RuntimeException('configuration_save_failed');
        }
    }

    /** Height divided by width of a Zabbix image, read once when a floor is saved. */
    public function imageAspect(string $imageid): ?float {
        $images = \API::Image()->get(['output'=>['imageid'], 'imageids'=>[$imageid], 'select_image'=>true]);
        if (!$images) {
            return null;
        }
        $size = @getimagesizefromstring(base64_decode((string) $images[0]['image']));
        return $size && $size[0] > 0 ? round($size[1] / $size[0], 5) : null;
    }
}
