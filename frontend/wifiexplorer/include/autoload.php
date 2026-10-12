<?php
/**
 * Package-local autoloader: does not modify Zabbix's core loader.
 *
 * Wi-Fi Explorer reuses Network Explorer's permission-aware gateway, envelope rules, freshness and findings, so it
 * loads that module's services from the sibling modules/networkexplorer directory. Without it the page says what is
 * missing instead of failing.
 */
spl_autoload_register(static function (string $class): void {
    $prefix = 'Modules\\WifiExplorer\\Services\\';
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

$networkExplorer = dirname(__DIR__, 2).'/networkexplorer/include/autoload.php';
if (is_file($networkExplorer)) {
    require_once $networkExplorer;
}
unset($networkExplorer);
