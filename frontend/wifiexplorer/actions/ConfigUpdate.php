<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

use Modules\WifiExplorer\Services\WifiConfigError;
use Modules\WifiExplorer\Services\WifiConfigStore;

/** Validates and saves the configuration document; on any problem nothing is saved and every problem is listed. */
final class ConfigUpdate extends ConfigBase {
    protected function checkInput(): bool {
        $valid = $this->validateInput(['config'=>'required|string']);
        if (!$valid) {
            $this->setResponse(new \CControllerResponseFatal());
        }
        return $valid;
    }

    protected function doAction(): void {
        $text = (string) $this->getInput('config');
        $store = new WifiConfigStore();
        try {
            $document = json_decode($text, true, 32, JSON_THROW_ON_ERROR);
            $store->save(self::prepare($document, $store));
            $response = new \CControllerResponseRedirect((new \CUrl('zabbix.php'))
                ->setArgument('action', 'wifiexplorer.config.edit'));
            \CMessageHelper::setSuccessTitle(_('Wi-Fi configuration saved'));
            $this->setResponse($response);
            return;
        }
        catch (\JsonException $error) {
            $problems = [_s('The text is not valid JSON: %1$s', $error->getMessage())];
        }
        catch (WifiConfigError $error) {
            $problems = $error->problems;
        }
        catch (\RuntimeException $error) {
            $problems = [_('The configuration could not be saved.')];
        }
        $response = new \CControllerResponseData($this->editorData($text, $problems));
        $response->setTitle(_('Wi-Fi Explorer configuration'));
        $this->setResponse($response);
    }
}
