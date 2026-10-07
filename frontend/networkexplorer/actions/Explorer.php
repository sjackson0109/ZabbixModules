<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

final class Explorer extends Base {
    protected function doAction(): void {
        try {
            $data = $this->network();
        }
        catch (\Throwable $error) {
            $data = $this->error($error);
        }
        $data['selected_hostid'] = (string) $this->getInput('hostid', '');
        $uid = $this->getInput('interface_uid', '');
        $data['selected_uid'] = \Modules\NetworkExplorer\Services\EnvelopeValidator::validUid($uid) ? $uid : '';
        $data['management_cidr'] = $this->getInput('management_cidr', '');
        $response = new \CControllerResponseData($data);
        $response->setTitle(_('Network Explorer'));
        $this->setResponse($response);
    }
}
