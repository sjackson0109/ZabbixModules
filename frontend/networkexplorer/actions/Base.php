<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

require_once dirname(__DIR__).'/include/autoload.php';

use Modules\NetworkExplorer\Services\Errors;
use Modules\NetworkExplorer\Services\NetworkScope;
use Modules\NetworkExplorer\Services\NetworkService;

abstract class Base extends \CController {
    protected function init(): void {
        // These routes are read-only, with authorisation repeated per request.
        $this->disableCsrfValidation();
    }

    protected function checkInput(): bool {
        $valid = $this->validateInput(['hostid'=>'db hosts.hostid', 'hostids'=>'array_db hosts.hostid',
            'interface_uid'=>'string', 'interface_hostid'=>'db hosts.hostid', 'management_cidr'=>'string',
            'site'=>'string', 'domain'=>'string', 'view'=>'in layer2,stp,vlan', 'vlan'=>'int32',
            'report'=>'string', 'format'=>'string']);
        if (!$valid) {
            $this->setResponse(new \CControllerResponseFatal());
        }
        return $valid;
    }

    protected function checkPermissions(): bool {
        return $this->checkAccess(\CRoleHelper::UI_MONITORING_HOSTS);
    }

    /** The request's scope; every route builds the graph, findings, quality and exports from the same one. */
    protected function scope(bool $listCandidates = false): NetworkScope {
        $ids = $this->getInput('hostids', []);
        if ($this->hasInput('hostid') && (string) $this->getInput('hostid') !== '0') {
            $ids[] = (string) $this->getInput('hostid');
        }
        return NetworkScope::create($ids, $this->getInput('management_cidr', ''), $this->getInput('site', ''),
            $this->getInput('domain', ''), $listCandidates);
    }

    protected function network(): array {
        return NetworkService::create()->buildScope($this->scope());
    }

    protected function error(\Throwable $error): array {
        return ['error'=>Errors::code($error)];
    }
}
