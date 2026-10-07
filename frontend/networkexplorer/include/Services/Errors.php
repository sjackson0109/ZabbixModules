<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * The only error text that reaches a user. Services throw these codes; anything else (API, database or
 * device text) is reported as dataset_read_failed so native messages and device strings are never echoed.
 */
final class Errors {
    public const READ_FAILED = 'dataset_read_failed';

    /** @return array<string, string> code => translated message */
    private static function messages(): array {
        return [
            'invalid_hostid'=>_('Invalid host selection.'),
            'invalid_itemid'=>_('Invalid item selection.'),
            'item_unavailable'=>_('The selected interface item is unavailable or inaccessible.'),
            'item_not_interface'=>_('Select a Network Explorer interface operational item.'),
            'item_wrong_host'=>_('The selected item belongs to a different host.'),
            'invalid_management_cidr'=>_('Enter valid IPv4 or IPv6 management subnet ranges.'),
            'invalid_report'=>_('Unknown report.'),
            'invalid_format'=>_('Unknown export format.'),
            'host_budget_exceeded'=>_s('The host scope exceeds the %1$s-host limit. Select a narrower scope.',
                Limits::HOSTS),
            'interface_budget_exceeded'=>_('The interface scope exceeds the reader limit. Select a narrower scope.'),
            'item_budget_exceeded'=>_('The item scope exceeds the reader limit. Select a narrower scope.'),
            'history_budget_exceeded'=>_('The history request exceeds the reader limit. Select a narrower scope.'),
            'response_budget_exceeded'=>_('The response exceeds the reader limit. Select a narrower scope.'),
            self::READ_FAILED=>_('Network observations could not be loaded. Check module installation and server diagnostics.')
        ];
    }

    public static function code(\Throwable $error): string {
        $code = $error->getMessage();
        return array_key_exists($code, self::messages()) ? $code : self::READ_FAILED;
    }

    public static function message(string $code): string {
        $messages = self::messages();
        return $messages[$code] ?? $messages[self::READ_FAILED];
    }
}
