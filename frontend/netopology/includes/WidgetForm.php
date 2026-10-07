<?php
namespace Modules\NeTopology\Includes;
use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldMultiSelectOverrideHost,CWidgetFieldSelect,CWidgetFieldTextBox,CWidgetFieldMultiSelectItem};
class WidgetForm extends CWidgetForm {
 public function addFields(): self {
  return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
 ->addField(new CWidgetFieldTextBox('management_cidr', _('Management subnet (annotation)')));
 }
}
