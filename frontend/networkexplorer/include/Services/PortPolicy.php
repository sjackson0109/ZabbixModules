<?php
declare(strict_types=1);
namespace Modules\NetworkExplorer\Services;

final class PortPolicy {
    private const SOURCES = ['policy'=>'the configured expected speed',
        'negotiable'=>'the fastest speed both ends advertise',
        'uplink_capability'=>'the port\'s fastest speed, expected on a link to another bridge'];

    public function evaluate(array $interface, string $freshness = 'unknown'): array {
        $admin = $interface['admin_status'] ?? 'unknown';
        $oper = $interface['oper_status'] ?? 'unknown';
        $adminUp = in_array($admin, ['up',1,'1'], true);
        $adminDown = in_array($admin, ['down',2,'2','disabled'], true);
        $operUp = in_array($oper, ['up',1,'1'], true);
        $expected = $interface['expected_speed_bps'] ?? null;
        $actual = $interface['speed_bps'] ?? null;
        $expected = is_numeric($expected) && $expected > 0 ? (float) $expected : null;
        $actual = is_numeric($actual) && $actual >= 0 ? (float) $actual : null;
        $result = ['state'=>'unknown', 'reason'=>'Interface state is unavailable.',
            'expected_speed_bps'=>$expected,
            'expected_speed_source'=>$expected === null ? 'unknown'
                : (isset(self::SOURCES[$interface['expected_speed_source'] ?? null])
                    ? $interface['expected_speed_source'] : 'policy'),
            'freshness'=>$freshness, 'speed_degraded'=>false, 'speed_warning_confirmed'=>false, 'duplex_mismatch'=>false];
        if ($adminDown) {
            return array_replace($result, ['state'=>'disabled', 'reason'=>'Administratively disabled.']);
        }
        if ($freshness !== 'current') {
            return array_replace($result, ['state'=>'unknown', 'reason'=>'Observation is '.$freshness.'.']);
        }
        if ($adminUp && in_array($oper, ['down','lower_layer_down','not_present',2,6,7,'2','6','7'], true)) {
            return array_replace($result, ['state'=>'down', 'reason'=>'Operationally down.']);
        }
        if (!$adminUp || !$operUp) {
            return $result;
        }
        // A link can be both slow and mismatched (Appendix A: 100M half against a full-duplex 1G partner).
        $result['duplex_mismatch'] = ($interface['duplex'] ?? null) === 'half' && ($interface['peer_duplex'] ?? null) === 'full';
        if ($expected !== null && $actual !== null && $actual < $expected) {
            // A snapshot holds a single speed observation and no persistence evidence;
            // the native trigger, not this view, decides whether it is sustained.
            return array_replace($result, ['state'=>'speed_observation',
                'speed_degraded'=>true,
                'reason'=>'Observed speed is below '.self::SOURCES[$result['expected_speed_source']]
                    .'; persistence is unconfirmed.']);
        }
        if (($interface['duplex'] ?? null) === 'half') {
            return array_replace($result, ['state'=>'duplex_observation',
                'reason'=>$result['duplex_mismatch'] ? 'Half duplex against a full-duplex peer (from LLDP).'
                    : 'Half duplex observed; mismatch requires peer or policy evidence.']);
        }
        return array_replace($result, ['state'=>'normal', 'reason'=>$expected === null
            ? 'Operationally up; intended speed is unknown.' : 'Operationally up at intended speed.']);
    }
}
