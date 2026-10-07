<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

final class Data extends Base {
    protected function doAction(): void {
        try {
            $data = $this->network();
        }
        catch (\Throwable $error) {
            $data = $this->error($error);
        }
        $this->setResponse((new \CControllerResponseData([
            'main_block'=>json_encode($data, JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE)
        ]))->disableView());
    }
}
