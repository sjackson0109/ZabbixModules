<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

require_once dirname(__DIR__).'/include/autoload.php';

use Modules\WifiExplorer\Services\WifiErrors;
use Modules\WifiExplorer\Services\WifiScope;
use Modules\WifiExplorer\Services\WifiService;

abstract class Base extends \CController {
    /** Address-bar fields; WifiScope validates each one. */
    protected const FIELDS = ['site', 'ap', 'view', 'floor', 'overlay', 'band', 'ssid', 'client', 'fail_host', 'fail_if',
        'event', 'q', 'range'];

    private ?WifiService $service = null;

    protected function init(): void {
        // These routes are read-only, with authorisation repeated per request.
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        $valid = $this->validateInput(array_fill_keys(static::FIELDS, 'string'));
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

    /** The request's fields as given, for links that keep the current view. */
    protected function request(): array {
        $request = [];
        foreach (static::FIELDS as $field) {
            $request[$field] = (string) $this->getInput($field, '');
        }
        return $request;
    }

    /** One service per request, so the configuration is loaded once. */
    protected function service(): WifiService {
        return $this->service ??= WifiService::create();
    }

    protected function scope(): WifiScope {
        $request = $this->request();
        return WifiScope::create($request['site'], $request['ap'], $request);
    }

    protected function wifi(): array {
        if (!self::networkExplorerInstalled()) {
            return ['error'=>WifiErrors::NETWORK_EXPLORER_MISSING];
        }
        try {
            return $this->service()->build($this->scope());
        }
        catch (\Throwable $error) {
            return ['error'=>WifiErrors::code($error)];
        }
    }
}
