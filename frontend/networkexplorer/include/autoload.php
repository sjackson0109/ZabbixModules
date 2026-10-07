<?php
/** Package-local autoloader: does not modify Zabbix's core loader. */
spl_autoload_register(static function (string $class): void {
    $prefix = 'Modules\\NetworkExplorer\\Services\\';
    if (strncmp($class, $prefix, strlen($prefix)) !== 0) {
        return;
    }
    $name = substr($class, strlen($prefix));
    if (preg_match('/^[A-Za-z][A-Za-z0-9]*$/D', $name)) {
        $path = __DIR__.'/Services/'.$name.'.php';
        if (is_file($path)) {
            require_once $path;
        }
    }
});
