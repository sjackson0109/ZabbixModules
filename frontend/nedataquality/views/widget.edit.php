<?php
$form = new CWidgetFormView($data);
$form->addField(new CWidgetFieldMultiSelectOverrideHostView($data['fields']['override_hostid']));
$form->show();
