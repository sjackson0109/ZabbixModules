<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

use Modules\NetworkExplorer\Services\EnvelopeValidator;
use Modules\NetworkExplorer\Services\NetworkService;

/**
 * Monitoring -> Network Explorer: the network-wide view. Without parameters it shows every permitted switch;
 * site, domain, management subnet and seed device narrow it. Needs no dashboard.
 */
final class Explorer extends Base {
    protected function doAction(): void {
        $service = NetworkService::create();
        try {
            $data = $service->buildScope($this->scope(true));
        }
        catch (\Throwable $error) {
            $data = $this->error($error);
        }
        try {
            $data['options'] = $service->scopeOptions();
        }
        catch (\Throwable $error) {
            $data['options'] = ['sites'=>[], 'domains'=>[], 'truncated'=>false];
        }
        $hostid = (string) $this->getInput('hostid', '0');
        $uid = (string) $this->getInput('interface_uid', '');
        $vlan = (int) $this->getInput('vlan', 0);
        $data['request'] = [
            'hostid'=>$hostid === '0' ? '' : $hostid,
            'site'=>(string) $this->getInput('site', ''),
            'domain'=>(string) $this->getInput('domain', ''),
            'management_cidr'=>(string) $this->getInput('management_cidr', ''),
            'view'=>(string) $this->getInput('view', 'layer2'),
            'vlan'=>$vlan >= 1 && $vlan <= 4094 ? $vlan : null,
            // A deep link names an interface on the seed unless it names its host.
            'interface_hostid'=>EnvelopeValidator::validUid($uid)
                ? (string) $this->getInput('interface_hostid', $hostid === '0' ? '' : $hostid) : '',
            'interface_uid'=>EnvelopeValidator::validUid($uid) ? $uid : ''
        ];
        $response = new \CControllerResponseData($data);
        $response->setTitle(_('Network Explorer'));
        $this->setResponse($response);
    }
}
