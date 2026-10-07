<?php
$form = new CWidgetFormView($data);
$form->addField(new CWidgetFieldMultiSelectOverrideHostView($data['fields']['override_hostid']));
$form->addField(new CWidgetFieldSelectView($data['fields']['layout']));
$form->show();
