<?php
declare(strict_types=1);

require_once __DIR__.'/../../frontend/networkexplorer/include/autoload.php';
require_once __DIR__.'/zabbix_stubs.php';

use Modules\NetworkExplorer\Services\ApiGateway;
use Modules\NetworkExplorer\Services\Errors;
use Modules\NetworkExplorer\Services\WidgetPayload;

/** Records every frontend API call and answers it from canned rows, standing in for the logged-in user's API. */
final class StubApiObject {
    public array $calls = [];

    public function __construct(private array $rows) {
    }

    public function get(array $options): array {
        $this->calls[] = $options;
        return $this->rows;
    }
}

final class API {
    public static array $objects = [];

    public static function __callStatic(string $name, array $args): StubApiObject {
        return self::$objects[$name] ??= new StubApiObject([]);
    }
}

final class StubHistory {
    public array $requested = [];

    public function getLastValues(array $items, int $limit, int $period): array {
        array_push($this->requested, ...$items);
        return [];
    }
}

final class Manager {
    public static ?StubHistory $history = null;

    public static function History(): StubHistory {
        return self::$history ??= new StubHistory();
    }
}

/** The API gateway's own authorisation filter, and the widget payload entry point. */
(static function (): void {
    $checks = 0;
    $assert = static function (bool $ok, string $message) use (&$checks): void {
        ++$checks;
        if (!$ok) { throw new RuntimeException($message); }
    };

    // Only hosts and items the user's API calls returned can be read further.
    API::$objects = ['Host'=>new StubApiObject([['hostid'=>'1','host'=>'a','name'=>'a','macros'=>[
            ['macro'=>'{$NE.IF.EXPECTED_SPEED:"Gi1"}','value'=>'1G','type'=>'0'],
            ['macro'=>'{$NE.IF.EXPECTED_SPEED:"Gi2"}','value'=>'secret','type'=>'1'],
            ['macro'=>'{$SNMP_COMMUNITY}','value'=>'public','type'=>'0']]]]),
        'Item'=>new StubApiObject([['itemid'=>'10','hostid'=>'1','key_'=>'ne.raw.lldp','value_type'=>'4']])];
    Manager::$history = null;
    $gateway = new ApiGateway();
    $hosts = $gateway->hosts();
    $assert(array_column($hosts[0]['macros'], 'macro') === ['{$NE.IF.EXPECTED_SPEED:"Gi1"}'],
        'Only plain-text expected-speed macros leave the gateway.');
    $gateway->items(['1', '2']);
    $assert(API::$objects['Item']->calls[0]['hostids'] === ['1'], 'Items are read only for authorised hosts.');
    $gateway->history([['itemid'=>'10','value_type'=>'0'], ['itemid'=>'99','value_type'=>'4']], 1);
    $assert(Manager::History()->requested === [['itemid'=>'10','hostid'=>'1','key_'=>'ne.raw.lldp','value_type'=>'4']],
        'History reads only authorised items, with their authorised value type.');
    $assert((new ApiGateway())->items(['1']) === [], 'A new gateway has authorised no hosts.');
    (new ApiGateway())->hosts([], [['tag'=>'site', 'value'=>'east'], ['tag'=>'ne.domain', 'value'=>'d-a']]);
    $call = end(API::$objects['Host']->calls);
    $assert($call['evaltype'] === TAG_EVAL_TYPE_AND_OR && $call['tags'] === [
            ['tag'=>'site', 'value'=>'east', 'operator'=>TAG_OPERATOR_EQUAL],
            ['tag'=>'ne.domain', 'value'=>'d-a', 'operator'=>TAG_OPERATOR_EQUAL]] && $call['monitored_hosts'],
        'Site and domain filters are exact tag matches inside the user\'s own host.get.');
    API::$objects['Host'] = new StubApiObject([['hostid'=>'1', 'tags'=>[['tag'=>'site', 'value'=>'east'],
        ['tag'=>'owner', 'value'=>'private']]]]);
    $tagged = (new ApiGateway())->tagged(['site', 'ne.domain']);
    $assert($tagged === [['hostid'=>'1', 'tags'=>[['tag'=>'site', 'value'=>'east']]]]
        && API::$objects['Host']->calls[0]['tags'][0]['operator'] === TAG_OPERATOR_EXISTS,
        'Selector population reads only the scope tags.');

    // Widget payloads: only fixed messages reach the browser.
    API::$objects = [];
    $payload = WidgetPayload::build([], true, false);
    $assert(($payload['message'] ?? '') === 'Select a host using the widget configuration or Host navigator.'
        && $payload['scope']['layout'] === 'auto' && $payload['scope']['colours'] === [],
        'A single-host widget without a host asks for one.');
    $payload = WidgetPayload::build(['override_hostid'=>['0x1']], false, false);
    $assert($payload['message'] === Errors::message('invalid_hostid'), 'A malformed host ID is rejected.');
    API::$objects['Item'] = new StubApiObject([['itemid'=>'7','hostid'=>'2','key_'=>'ne.if.oper["if-x"]']]);
    $payload = WidgetPayload::build(['override_hostid'=>['1'], 'itemid'=>['7']], true, false);
    $assert($payload['message'] === Errors::message('item_wrong_host'), 'An item on another host is rejected.');
    API::$objects['Item'] = new StubApiObject([['itemid'=>'7','hostid'=>'2','key_'=>'system.uptime']]);
    $payload = WidgetPayload::build(['itemid'=>['7']], true, false);
    $assert($payload['message'] === Errors::message('item_not_interface'), 'Only interface items select a port.');
    $payload = WidgetPayload::build(['layout'=>4, 'layer'=>9, 'colour_down'=>'ff0000', 'colour_normal'=>'red'], true, true);
    $assert($payload['scope']['layout'] === 'stack' && $payload['scope']['layer'] === 'physical'
        && $payload['scope']['colours'] === ['down'=>'FF0000'], 'Form values map to known names and colours only.');

    $assert(Errors::code(new RuntimeException('SQL error near "secret"')) === Errors::READ_FAILED
        && Errors::code(new RuntimeException('host_budget_exceeded')) === 'host_budget_exceeded',
        'Unknown exception text is never echoed.');

    echo "Gateway authorisation and widget payload checks passed ($checks checks).\n";
})();
