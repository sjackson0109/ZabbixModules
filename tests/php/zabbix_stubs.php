<?php
declare(strict_types=1);

/** The subset of the Zabbix frontend runtime that the services use, for running them outside Zabbix. */
foreach (['INTERFACE_USE_IP'=>1, 'INTERFACE_TYPE_SNMP'=>2, 'INTERFACE_AVAILABLE_TRUE'=>1,
        'INTERFACE_AVAILABLE_FALSE'=>2, 'ITEM_VALUE_TYPE_TEXT'=>4, 'ZBX_MACRO_TYPE_TEXT'=>0,
        'TAG_EVAL_TYPE_AND_OR'=>0, 'TAG_EVAL_TYPE_OR'=>2, 'TAG_OPERATOR_EQUAL'=>1, 'TAG_OPERATOR_EXISTS'=>4] as $name => $value) {
    if (!defined($name)) {
        define($name, $value);
    }
}

if (!function_exists('_')) {
    function _(string $text): string {
        return $text;
    }
}

if (!function_exists('_s')) {
    function _s(string $format, ...$args): string {
        return vsprintf($format, $args);
    }
}
