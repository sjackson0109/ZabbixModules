<?php
$form = new CWidgetFormView($data);
$form->addField(new CWidgetFieldMultiSelectOverrideHostView($data['fields']['override_hostid']));
$form->addField(new CWidgetFieldMultiSelectItemView($data['fields']['itemid']));
$form->addField(new CWidgetFieldTextBoxView($data['fields']['interface_uid']));
$form->show();
