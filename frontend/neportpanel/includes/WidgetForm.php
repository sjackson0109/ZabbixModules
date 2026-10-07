<?php
namespace Modules\NePortPanel\Includes;
use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldColor,CWidgetFieldMultiSelectOverrideHost,CWidgetFieldSelect,CWidgetFieldTextBox,CWidgetFieldMultiSelectItem};
class WidgetForm extends CWidgetForm {
 /** Port state colours (spec §3.1); every state also keeps its label and icon. */
 public const COLOURS = ['normal'=>['287E3F', 'Normal'], 'degraded'=>['B37312', 'Degraded or observation'],
  'down'=>['B04444', 'Down'], 'disabled'=>['607080', 'Admin disabled'], 'unknown'=>['3A4752', 'No data']];
 public function addFields(): self {
  foreach (self::COLOURS as $state => [$default, $label]) {
   $this->addField((new CWidgetFieldColor('colour_'.$state, _($label).' '._('colour')))->setDefault($default));
  }
  return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
 ->addField((new CWidgetFieldSelect('layout', _('Physical layout'), [0=>_('Automatic'),1=>_('24 port'),2=>_('48 port'),3=>_('Mixed copper / fibre'),4=>_('Stack'),5=>_('Generic rows')]))->setDefault(0))
 ->addField((new CWidgetFieldSelect('layer', _('Default layer'), [0=>_('Physical'),1=>_('VLAN'),2=>_('STP'),3=>_('LLDP')]))->setDefault(0));
 }
}
