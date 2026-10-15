<?php
declare(strict_types=1);
namespace Modules\NePortPanel\Includes;

use Zabbix\Widgets\CWidgetForm;
use Zabbix\Widgets\Fields\{CWidgetFieldColor, CWidgetFieldMultiSelectOverrideHost, CWidgetFieldSelect};

class WidgetForm extends CWidgetForm {
    /**
     * Default port state colours (spec §3.1): the light theme's design tokens. Left at its default, a state follows
     * the Zabbix theme instead (the payload drops defaults); every state also keeps its label and icon.
     */
    public const COLOURS = ['normal'=>'26793C', 'degraded'=>'916000', 'down'=>'B04444', 'disabled'=>'5C6C7B',
        'unknown'=>'5C6C7B'];

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
