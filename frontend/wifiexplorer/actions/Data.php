<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

/** The same permission-filtered model as the page, as JSON. */
final class Data extends Base {
    private const JSON_FLAGS = JSON_UNESCAPED_SLASHES | JSON_INVALID_UTF8_SUBSTITUTE | JSON_THROW_ON_ERROR;

    protected function doAction(): void {
        $this->setResponse((new \CControllerResponseData(['main_block'=>json_encode($this->wifi(), self::JSON_FLAGS)]))
            ->disableView());
    }
}
