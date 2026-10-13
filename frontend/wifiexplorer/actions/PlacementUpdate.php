<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Actions;

use Modules\WifiExplorer\Services\WifiConfigError;
use Modules\WifiExplorer\Services\WifiConfigStore;
use Modules\WifiExplorer\Services\WifiEnvelopeValidator;

/**
 * Places one AP on a floor, or removes its placement, from the floor-plan view. Keyed by the AP's opaque ID; the
 * whole document is validated again before it is saved. Answers JSON.
 */
final class PlacementUpdate extends ConfigBase {
    private const JSON_FLAGS = JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR;

    protected function checkInput(): bool {
        $valid = $this->validateInput(['ap_uid'=>'required|string', 'floor_id'=>'string', 'x'=>'string', 'y'=>'string',
            'remove'=>'in 1']);
        if (!$valid) {
            $this->respond(['error'=>_('Invalid placement request.')]);
        }
        return $valid;
    }

    protected function doAction(): void {
        $apUid = (string) $this->getInput('ap_uid');
        if (!WifiEnvelopeValidator::validApUid($apUid)) {
            $this->respond(['error'=>_('Invalid AP ID.')]);
            return;
        }
        $store = new WifiConfigStore();
        try {
            $config = $store->load();
            if ($this->hasInput('remove')) {
                unset($config['placements'][$apUid]);
            }
            else {
                $x = filter_var($this->getInput('x', ''), FILTER_VALIDATE_FLOAT);
                $y = filter_var($this->getInput('y', ''), FILTER_VALIDATE_FLOAT);
                $config['placements'][$apUid] = ['floor_id'=>(string) $this->getInput('floor_id', ''),
                    'x'=>$x === false ? null : $x, 'y'=>$y === false ? null : $y];
            }
            $store->save(self::prepare(json_decode(json_encode(\Modules\WifiExplorer\Services\WifiConfig::export($config)),
                true), $store));
            $this->respond(['ok'=>true]);
        }
        catch (WifiConfigError $error) {
            $this->respond(['error'=>implode(' ', $error->problems)]);
        }
        catch (\RuntimeException $error) {
            $this->respond(['error'=>_('The placement could not be saved.')]);
        }
    }

    private function respond(array $body): void {
        $this->setResponse((new \CControllerResponseData(['main_block'=>json_encode($body, self::JSON_FLAGS)]))
            ->disableView());
    }
}
