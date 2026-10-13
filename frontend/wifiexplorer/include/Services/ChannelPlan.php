<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

/**
 * The spectrum a channel occupies, from the IEEE 802.11 channel plan: a primary channel number, its band and its
 * width give the bonded block in MHz. The block is derived, not observed, so anything built on it is inferred.
 *
 * Where the plan does not fix the block (a 40 MHz channel in 2.4 GHz, whose secondary may sit above or below, an
 * unknown width, or 80+80), only the primary 20 MHz is used: the radio occupies at least that much, so an overlap
 * found with it is real, and a wider overlap may be missed rather than invented.
 */
final class ChannelPlan {
    /** @return array{0: int, 1: int, 2: string}|null low and high edge in MHz, and the basis (block or primary) */
    public static function span(?string $band, ?int $channel, ?string $width): ?array {
        if ($band === null || $channel === null || $channel < 1) {
            return null;
        }
        $mhz = in_array($width, ['40', '80', '160'], true) ? (int) $width : 20;
        switch ($band) {
            case '2.4':
                if ($channel > 14) {
                    return null;
                }
                $centre = $channel === 14 ? 2484 : 2407 + 5 * $channel;
                return [$centre - 10, $centre + 10, 'primary'];
            case '5':
                if ($channel < 32 || $channel > 177) {
                    return null;
                }
                $anchor = $channel >= 149 ? 149 : ($channel >= 100 ? 100 : 36);
                return self::block(5000, $anchor, $channel, $mhz, $width);
            case '6':
                if ($channel > 233) {
                    return null;
                }
                return self::block(5950, 1, $channel, $mhz, $width);
        }
        return null;
    }

    /** Whether two spans share spectrum. */
    public static function overlaps(array $a, array $b): bool {
        return $a[0] < $b[1] && $b[0] < $a[1];
    }

    private static function block(int $base, int $anchor, int $channel, int $mhz, ?string $width): array {
        if ($mhz === 20 || $channel < $anchor) {
            $centre = $base + 5 * $channel;
            return [$centre - 10, $centre + 10, $width === '20' ? 'block' : 'primary'];
        }
        $step = intdiv($mhz, 5);
        $start = $anchor + intdiv($channel - $anchor, $step) * $step;
        $low = $base + 5 * $start - 10;
        return [$low, $low + $mhz, 'block'];
    }
}
