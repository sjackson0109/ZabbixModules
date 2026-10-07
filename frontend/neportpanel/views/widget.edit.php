<?php
use Modules\NePortPanel\Includes\WidgetForm;

$form = new CWidgetFormView($data);
$form->addField(new CWidgetFieldMultiSelectOverrideHostView($data['fields']['override_hostid']));
$form->addField(new CWidgetFieldSelectView($data['fields']['layout']));
$form->addField(new CWidgetFieldSelectView($data['fields']['layer']));
foreach (array_keys(WidgetForm::COLOURS) as $state) {
    $form->addField(new CWidgetFieldColorView($data['fields']['colour_'.$state]));
}
// 7.0 and 7.2 render a plain input that the form must turn into a colour picker; 7.4 renders its own picker.
if (version_compare(ZABBIX_VERSION, '7.4', '<')) {
    $form->addJavaScript("for (const input of document.querySelectorAll('#widget-dialogue-form .".ZBX_STYLE_COLOR_PICKER." input')) {\n"
        ." $(input).colorpicker({appendTo: '.overlay-dialogue-body', use_default: true});\n}");
}
$form->show();
