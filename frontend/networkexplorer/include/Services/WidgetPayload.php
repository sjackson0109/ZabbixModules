<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * Builds the payload every Network Explorer widget renders. Widgets call this only after confirming the base
 * module is enabled, so a missing module degrades to a message instead of a fatal error.
 */
final class WidgetPayload {
    private const LAYOUTS = ['auto', '24', '48', 'mixed', 'stack', 'generic'];
    private const LAYERS = ['physical', 'vlan', 'stp', 'lldp'];
    private const MODES = ['physical', 'vlan', 'stp'];
    private const STATE_COLOURS = ['normal', 'degraded', 'down', 'disabled', 'unknown'];
    private const ID = '/^[1-9][0-9]*$/D';
    /** The interface operational item that identifies a port; its key parameter is the interface UID. */
    private const INTERFACE_ITEM = '/^ne\.if\.oper\[([^\]\r\n]{1,128})\]$/D';

    /**
     * @param array $fields        the widget's form values
     * @param bool  $requiresHost  true when the widget shows a single host and has nothing to draw without one
     */
    public static function build(array $fields, bool $requiresHost, bool $templateDashboard): array {
        $scope = self::scope($fields);
        try {
            self::resolveItem($scope);
            if ($scope['hostid'] === '' && ($requiresHost || $templateDashboard)) {
                return ['scope'=>$scope, 'message'=>_('Select a host using the widget configuration or Host navigator.')];
            }
            $payload = NetworkService::create()->build($scope['hostid'] === '' ? [] : [$scope['hostid']],
                $scope['management_cidr']);
        }
        catch (\Throwable $error) {
            return ['scope'=>$scope, 'message'=>Errors::message(Errors::code($error))];
        }
        $payload['scope'] = array_replace($payload['scope'] ?? [], $scope);
        return $payload;
    }

    private static function scope(array $fields): array {
        $colours = [];
        foreach (self::STATE_COLOURS as $state) {
            $value = (string) ($fields['colour_'.$state] ?? '');
            if (preg_match('/^[0-9A-F]{6}$/iD', $value)) {
                $colours[$state] = strtoupper($value);
            }
        }
        return [
            'hostid'=>(string) ($fields['override_hostid'][0] ?? ''),
            'interface_uid'=>substr((string) ($fields['interface_uid'] ?? ''), 0, 128),
            'itemid'=>(string) ($fields['itemid'][0] ?? ''),
            'management_cidr'=>substr(trim((string) ($fields['management_cidr'] ?? '')), 0, 128),
            'layout'=>self::LAYOUTS[(int) ($fields['layout'] ?? 0)] ?? self::LAYOUTS[0],
            'layer'=>self::LAYERS[(int) ($fields['layer'] ?? 0)] ?? self::LAYERS[0],
            'mode'=>self::MODES[(int) ($fields['mode'] ?? 0)] ?? self::MODES[0],
            'colours'=>$colours
        ];
    }

    /** A selected interface item fixes both the host and the interface, after a permission-checked read. */
    private static function resolveItem(array &$scope): void {
        if ($scope['hostid'] !== '' && !preg_match(self::ID, $scope['hostid'])) {
            throw new \InvalidArgumentException('invalid_hostid');
        }
        if ($scope['itemid'] === '') {
            return;
        }
        if (!preg_match(self::ID, $scope['itemid'])) {
            throw new \InvalidArgumentException('invalid_itemid');
        }
        $items = \API::Item()->get(['output'=>['itemid', 'hostid', 'key_'], 'itemids'=>[$scope['itemid']]]);
        if (!$items) {
            throw new \RuntimeException('item_unavailable');
        }
        $item = reset($items);
        if (!preg_match(self::INTERFACE_ITEM, $item['key_'], $matches)) {
            throw new \InvalidArgumentException('item_not_interface');
        }
        if ($scope['hostid'] !== '' && $scope['hostid'] !== (string) $item['hostid']) {
            throw new \InvalidArgumentException('item_wrong_host');
        }
        $scope['hostid'] = (string) $item['hostid'];
        $scope['interface_uid'] = trim($matches[1], '"');
    }
}
