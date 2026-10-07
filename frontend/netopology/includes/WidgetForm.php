<?php
declare(strict_types=1);
namespace Modules\NeTopology\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldMultiSelectOverrideHost, CWidgetFieldSelect, CWidgetFieldTextBox};

class WidgetForm extends CWidgetForm {
    public function addFields(): self {
        return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
            ->addField(new CWidgetFieldTextBox('management_cidr', _('Management subnet (annotation)')))
            ->addField((new CWidgetFieldSelect('mode', _('Default overlay'),
                [0=>_('Physical'), 1=>_('VLAN'), 2=>_('STP')]))->setDefault(0));
    }
}
