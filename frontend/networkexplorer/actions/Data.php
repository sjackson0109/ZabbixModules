<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Actions;

final class Data extends Base {
    private const JSON_FLAGS = JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR;

    protected function doAction(): void {
        try {
            $body = json_encode($this->network(), self::JSON_FLAGS);
        }
        catch (\Throwable $error) {
            $body = json_encode($this->error($error), self::JSON_FLAGS);
        }
        $this->setResponse((new \CControllerResponseData(['main_block'=>$body]))->disableView());
    }
}
