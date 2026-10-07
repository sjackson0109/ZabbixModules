<?php
declare(strict_types=1);
namespace Modules\NePortPanel\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldColor, CWidgetFieldMultiSelectOverrideHost, CWidgetFieldSelect};

class WidgetForm extends CWidgetForm {
    /** Default port state colours (spec §3.1); every state also keeps its label and icon. */
    public const COLOURS = ['normal'=>'287E3F', 'degraded'=>'B37312', 'down'=>'B04444', 'disabled'=>'607080',
        'unknown'=>'3A4752'];

    public function addFields(): self {
        $labels = ['normal'=>_('Normal colour'), 'degraded'=>_('Degraded or observation colour'),
            'down'=>_('Down colour'), 'disabled'=>_('Admin disabled colour'), 'unknown'=>_('No data colour')];
        foreach (self::COLOURS as $state => $default) {
            $this->addField((new CWidgetFieldColor('colour_'.$state, $labels[$state]))->setDefault($default));
        }
        return $this->addField(new CWidgetFieldMultiSelectOverrideHost())
            ->addField((new CWidgetFieldSelect('layout', _('Physical layout'), [0=>_('Automatic'), 1=>_('24 port'),
                2=>_('48 port'), 3=>_('Mixed copper / fibre'), 4=>_('Stack'), 5=>_('Generic rows')]))->setDefault(0))
            ->addField((new CWidgetFieldSelect('layer', _('Default layer'),
                [0=>_('Physical'), 1=>_('VLAN'), 2=>_('STP'), 3=>_('LLDP')]))->setDefault(0));
    }
}
