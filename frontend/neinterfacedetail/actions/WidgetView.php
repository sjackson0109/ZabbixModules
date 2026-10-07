<?php
declare(strict_types=1);
namespace Modules\NeInterfaceDetail\Actions;

use APP;
use CControllerDashboardWidgetView;
use CControllerResponseData;
use Modules\NetworkExplorer\Services\WidgetPayload;

class WidgetView extends CControllerDashboardWidgetView {
    /** This widget describes one host and has nothing to show until one is selected. */
    private const REQUIRES_HOST = true;

    protected function doAction(): void {
        // The base module's services exist only while it is enabled; never load them from disk behind its back.
        $payload = APP::ModuleManager()->getModule('networkexplorer') === null
            ? ['message'=>_('Install and enable the Network Explorer base module.')]
            : WidgetPayload::build($this->fields_values, self::REQUIRES_HOST, $this->isTemplateDashboard());
        $this->setResponse(new CControllerResponseData([
            'name'=>$this->getInput('name', $this->widget->getDefaultName()),
            'user'=>['debug_mode'=>$this->getDebugMode()],
            'payload'=>$payload
        ]));
    }
}
