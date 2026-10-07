<?php
namespace Modules\NePortPanel\Includes;
use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldMultiSelectOverrideHost,CWidgetFieldSelect,CWidgetFieldTextBox,CWidgetFieldMultiSelectItem};
class WidgetForm extends CWidgetForm {
 public function addFields(): self {
  return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
 ->addField((new CWidgetFieldSelect('layout', _('Physical layout'), [0=>_('Automatic'),1=>_('24 port'),2=>_('48 port'),3=>_('Mixed copper / fibre'),4=>_('Stack'),5=>_('Generic rows')]))->setDefault(0));
 }
}
