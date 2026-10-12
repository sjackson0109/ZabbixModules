<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

/**
 * The one freshness and outcome rule for canonical datasets, shared by Network Explorer's reader and Wi-Fi
 * Explorer's: a stale observation is never current, a failed attempt keeps the last complete observation as
 * retained evidence, and only stable error codes leave the server.
 */
final class DatasetQuality {
    /**
     * Status, freshness and error codes of one dataset on one host.
     *
     * @param array|null  $envelope the retained snapshot (the last complete one, else the latest decoded one)
     * @param array|null  $attempt  the newest attempt of any outcome
     * @param string|null $failure  a reader-detected failure code (unreadable value, unsupported or disabled item)
     * @param int         $ttl      seconds after which an observation is stale
     */
    public static function describe(?array $envelope, ?array $attempt, ?string $failure, int $ttl, int $now): array {
        $observed = $envelope['observed_at'] ?? null;
        $epoch = $observed !== null ? strtotime($observed) : false;
        $freshness = 'unknown';
        $errors = [];
        if ($epoch !== false) {
            if ($epoch > $now + 60) {
                $errors[] = 'clock_skew';
            }
            else {
                $freshness = $now - $epoch > $ttl ? 'stale' : 'current';
            }
        }
        $latest = $attempt !== null && ($envelope === null
            || strtotime($attempt['attempted_at']) >= strtotime($envelope['attempted_at']))
            ? $attempt : $envelope;
        $status = $latest['status'] ?? 'unknown';
        if ($failure !== null) {
            $status = 'failed';
            $errors[] = $failure;
        }
        foreach (($latest['errors'] ?? []) as $error) {
            // Raw device/collector exception strings may contain hidden peer data.
            // Only stable bounded error identifiers are returned to the browser.
            $code = is_array($error) ? ($error['code'] ?? null) : $error;
            if (is_string($code) && preg_match('/^[a-z][a-z0-9_]{0,63}$/D', $code)) {
                $errors[] = $code;
            }
        }
        $warnings = [];
        foreach (($latest['warnings'] ?? []) as $warning) {
            if (is_string($warning['code'] ?? null)) {
                $warnings[] = $warning['code'];
            }
        }
        if ($envelope['inventory_stale'] ?? false) {
            $errors[] = 'inventory_stale';
        }
        return ['status'=>$status,
            'capability'=>$latest['capability']['state'] ?? 'unknown', 'freshness'=>$freshness,
            'attempted_at'=>$latest['attempted_at'] ?? null, 'observed_at'=>$observed,
            'age_seconds'=>$epoch !== false ? max(0, $now - $epoch) : null,
            'complete'=>$envelope['complete'] ?? false, 'retained'=> $envelope !== null
                && $latest !== null && $latest['status'] !== 'ok',
            'errors'=>array_values(array_unique($errors)), 'warnings'=>array_values(array_unique($warnings))];
    }

    private function __construct() {
    }
}
