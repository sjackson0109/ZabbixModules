<?php
declare(strict_types=1);
namespace Modules\NeFindings\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\CWidgetFieldMultiSelectOverrideHost;

class WidgetForm extends CWidgetForm {
    public function addFields(): self {
        return $this->addField(new CWidgetFieldMultiSelectOverrideHost());
    }
}
