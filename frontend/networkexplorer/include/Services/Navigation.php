<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

final class Navigation {
    public static function dashboard(string $hostid, ?string $uid = null, ?string $dashboardid = null): string {
        if (!preg_match('/^[1-9][0-9]*$/D', $hostid)
                || $dashboardid !== null && !preg_match('/^[1-9][0-9]*$/D', $dashboardid)
                || $uid !== null && !EnvelopeValidator::validUid($uid)) {
            throw new \InvalidArgumentException('invalid_navigation_context');
        }
        $params = ['action'=>'host.dashboard.view','hostid'=>$hostid];
        if ($dashboardid !== null) {
            $params['dashboardid'] = $dashboardid;
        }
        $url = 'zabbix.php?'.http_build_query($params, '', '&', PHP_QUERY_RFC3986);
        // Omit dashboardid unless selected for THIS host. Core resolves that
        // host's permitted inherited dashboard rather than reusing an origin ID.
        return $uid !== null ? $url.'#ne='.rawurlencode(json_encode(['hostid'=>$hostid,'uid'=>$uid],
            JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR)) : $url;
    }

    public static function explorer(string $hostid, ?string $uid = null): string {
        self::dashboard($hostid, $uid);
        return 'zabbix.php?'.http_build_query(['action'=>'networkexplorer.view','hostid'=>$hostid]
            + ($uid !== null ? ['interface_uid'=>$uid] : []), '', '&', PHP_QUERY_RFC3986);
    }
}
