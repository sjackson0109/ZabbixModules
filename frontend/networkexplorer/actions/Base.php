<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

require_once dirname(__DIR__).'/include/autoload.php';

use Modules\NetworkExplorer\Services\Errors;
use Modules\NetworkExplorer\Services\NetworkService;

abstract class Base extends \CController {
    protected function init(): void {
        // These routes are read-only, with authorisation repeated per request.
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        $valid = $this->validateInput(['hostid'=>'db hosts.hostid', 'hostids'=>'array_db hosts.hostid',
            'interface_uid'=>'string', 'management_cidr'=>'string', 'report'=>'string', 'format'=>'string']);
        if (!$valid) {
            $this->setResponse(new \CControllerResponseFatal());
        }
        return $valid;
    }

    protected function checkPermissions(): bool {
        return $this->checkAccess(\CRoleHelper::UI_MONITORING_HOSTS);
    }

    protected function network(): array {
        $ids = $this->getInput('hostids', []);
        if ($this->hasInput('hostid')) {
            $ids[] = (string) $this->getInput('hostid');
        }
        return NetworkService::create()->build(
            $ids, $this->getInput('management_cidr', ''));
    }

    protected function error(\Throwable $error): array {
        return ['error'=>Errors::code($error)];
    }
}
