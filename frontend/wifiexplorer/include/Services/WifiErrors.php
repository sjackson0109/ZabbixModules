<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/** The only error text that reaches a user; anything else is reported as dataset_read_failed. */
final class WifiErrors {
    public const READ_FAILED = 'dataset_read_failed';
    public const NETWORK_EXPLORER_MISSING = 'network_explorer_missing';

    /** @return array<string, string> */
    private static function messages(): array {
        return [
            'invalid_scope_filter'=>_('Invalid site selection.'),
            'owner_budget_exceeded'=>_s('More than %1$s Wi-Fi data sources are visible. Select a site to narrow the view.',
                WifiLimits::OWNER_HOSTS),
            'ap_budget_exceeded'=>_s('This scope holds more than %1$s access points. Select a site to narrow the view.',
                WifiLimits::DISPLAY_APS),
            'item_budget_exceeded'=>_('The item scope exceeds the reader limit. Select a site to narrow the view.'),
            'history_budget_exceeded'=>_('The history request exceeds the reader limit. Select a site to narrow the view.'),
            'response_budget_exceeded'=>_('The response exceeds the reader limit. Select a site to narrow the view.'),
            self::NETWORK_EXPLORER_MISSING=>_('Wi-Fi Explorer needs the Network Explorer module installed alongside it (modules/networkexplorer).'),
            self::READ_FAILED=>_('Wi-Fi observations could not be loaded. Check module installation and server diagnostics.')
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
