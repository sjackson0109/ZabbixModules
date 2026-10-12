<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

require_once dirname(__DIR__).'/include/autoload.php';

use Modules\WifiExplorer\Services\WifiErrors;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

abstract class Base extends \CController {
    protected function init(): void {
        // These routes are read-only, with authorisation repeated per request.
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        $valid = $this->validateInput(['site'=>'string', 'ap'=>'string']);
        if (!$valid) {
            $this->setResponse(new \CControllerResponseFatal());
        }
        return $valid;
    }

    protected function checkPermissions(): bool {
        return $this->checkAccess(\CRoleHelper::UI_MONITORING_HOSTS);
    }

    /** Wi-Fi Explorer reads through Network Explorer's gateway and validators; without them it says so. */
    protected static function networkExplorerInstalled(): bool {
        return class_exists('Modules\NetworkExplorer\Services\ApiGateway');
    }

    protected function scope(): WifiScope {
        return WifiScope::create((string) $this->getInput('site', ''), (string) $this->getInput('ap', ''));
    }

    protected function wifi(): array {
        if (!self::networkExplorerInstalled()) {
            return ['error'=>WifiErrors::NETWORK_EXPLORER_MISSING];
        }
        try {
            return WifiService::create()->build($this->scope());
        }
        catch (\Throwable $error) {
            return ['error'=>WifiErrors::code($error)];
        }
    }
}
