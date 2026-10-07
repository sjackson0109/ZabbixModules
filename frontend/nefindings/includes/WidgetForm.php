<?php
namespace Modules\NeFindings\Includes;
use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldMultiSelectOverrideHost,CWidgetFieldSelect,CWidgetFieldTextBox,CWidgetFieldMultiSelectItem};
class WidgetForm extends CWidgetForm {
 public function addFields(): self {
  return $this->addField(new CWidgetFieldMultiSelectOverrideHost());
 }
}
