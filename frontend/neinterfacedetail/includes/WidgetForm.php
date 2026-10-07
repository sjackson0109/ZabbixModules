<?php
namespace Modules\NeInterfaceDetail\Includes;
use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldMultiSelectOverrideHost,CWidgetFieldSelect,CWidgetFieldTextBox,CWidgetFieldMultiSelectItem};
class WidgetForm extends CWidgetForm {
 public function addFields(): self {
  return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
 ->addField((new CWidgetFieldMultiSelectItem('itemid', _('Interface operational item')))->setMultiple(false))
 ->addField(new CWidgetFieldTextBox('interface_uid', _('Interface UID (fallback)')));
 }
}
