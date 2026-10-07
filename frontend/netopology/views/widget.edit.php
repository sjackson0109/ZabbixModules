<?php
$form = new CWidgetFormView($data);
$form->addField(new CWidgetFieldMultiSelectOverrideHostView($data['fields']['override_hostid']));
$form->addField(new CWidgetFieldTextBoxView($data['fields']['management_cidr']));
$form->show();
