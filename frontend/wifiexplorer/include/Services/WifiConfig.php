<?php
declare(strict_types=1);
namespace Modules\WifiExplorer\Services;

use Modules\NetworkExplorer\Services\NetworkScope;

/**
 * Operator-declared Wi-Fi intent and placement: floors and their plan images, AP positions, SSID-to-VLAN intent,
 * event definitions and known external BSSIDs. It is configuration, never inferred from observations or history
 * (requirements sections 7.1 and 17), and it holds no secret: no PSK, RADIUS secret or credential has a field here.
 *
 * The document lives in the module's own configuration (the `wifi` key), which only a Super admin can change.
 * Every reader sees only the parts that belong to sites and APs they can already see.
 */
final class WifiConfig {
    public const VERSION = 1;
    /** Bytes of the normalised JSON document, before it is stored. */
    public const MAX_BYTES = 1000000;
    /**
     * Bytes the stored form may take in the module's configuration, a 65,535-byte TEXT column. Small documents are
     * stored as they are; larger ones are packed (see pack()), which fits about 2,300 AP placements (about 750 unpacked).
     */
    public const MAX_STORED_BYTES = 64000;
    private const PACKED = 'wifi-z1:';
    public const MAX_FLOORS = 200;
    public const MAX_PLACEMENTS = 5000;
    public const MAX_SSIDS = 200;
    public const MAX_EVENTS = 100;
    public const MAX_KNOWN = 1000;
    private const ID = '/^[a-z0-9][a-z0-9_-]{0,63}$/D';
    private const BANDS = ['2.4', '5', '6'];

    private function __construct() {
    }

    public static function empty(): array {
        return ['version'=>self::VERSION, 'floors'=>[], 'placements'=>[], 'ssids'=>[], 'events'=>[],
            'known_bssids'=>[]];
    }

    /**
     * Validates and normalises a document. Unknown keys are rejected so a typo is reported, not ignored.
     * @throws WifiConfigError listing every problem found
     */
    public static function normalise($document): array {
        $errors = [];
        if (!is_array($document) || ($document !== [] && array_keys($document) === range(0, count($document) - 1))) {
            throw new WifiConfigError([_('The configuration must be a JSON object.')]);
        }
        foreach (array_diff(array_keys($document), ['version', 'floors', 'placements', 'ssids', 'events', 'known_bssids'])
                as $key) {
            $errors[] = _s('Unknown key "%1$s".', (string) $key);
        }
        if (isset($document['version']) && $document['version'] !== self::VERSION) {
            $errors[] = _s('version must be %1$s.', self::VERSION);
        }
        $out = self::empty();
        $floors = self::list($document, 'floors', self::MAX_FLOORS, $errors);
        foreach ($floors as $i => $floor) {
            $at = 'floors['.$i.']';
            if (!self::fields($floor, ['floor_id', 'site', 'building', 'name', 'order', 'imageid', 'aspect', 'width_m'],
                    $at, $errors)) {
                continue;
            }
            $id = self::id($floor['floor_id'] ?? null, $at.'.floor_id', $errors);
            $row = ['floor_id'=>$id, 'site'=>self::site($floor['site'] ?? null, $at.'.site', $errors, false),
                'building'=>self::text($floor['building'] ?? '', 128, $at.'.building', $errors, true),
                'name'=>self::text($floor['name'] ?? null, 128, $at.'.name', $errors, false),
                'order'=>self::int($floor['order'] ?? 0, -100, 1000, $at.'.order', $errors),
                'imageid'=>null, 'aspect'=>null,
                'width_m'=>self::number($floor['width_m'] ?? null, 1, 10000, $at.'.width_m', $errors, true)];
            if (isset($floor['imageid'])) {
                $image = is_int($floor['imageid']) ? (string) $floor['imageid'] : $floor['imageid'];
                if (!is_string($image) || !preg_match('/^[1-9][0-9]{0,19}$/D', $image)) {
                    $errors[] = _s('%1$s must be a Zabbix image ID.', $at.'.imageid');
                }
                $row['imageid'] = is_string($image) ? $image : null;
            }
            $row['aspect'] = self::number($floor['aspect'] ?? null, 0.05, 20, $at.'.aspect', $errors, true);
            if ($id !== null && isset($out['floors'][$id])) {
                $errors[] = _s('Floor "%1$s" is defined twice.', $id);
            }
            if ($id !== null) {
                $out['floors'][$id] = $row;
            }
        }
        $placements = $document['placements'] ?? [];
        if (!is_array($placements) || $placements !== [] && array_keys($placements) === range(0, count($placements) - 1)) {
            $errors[] = _('placements must be an object keyed by AP ID.');
            $placements = [];
        }
        if (count($placements) > self::MAX_PLACEMENTS) {
            $errors[] = _s('At most %1$s AP placements.', self::MAX_PLACEMENTS);
            $placements = [];
        }
        foreach ($placements as $apUid => $place) {
            $at = 'placements.'.$apUid;
            if (!WifiEnvelopeValidator::validApUid($apUid)) {
                $errors[] = _s('%1$s: placements are keyed by AP ID (ap-...), never by name or MAC address.', $at);
                continue;
            }
            if (!self::fields($place, ['floor_id', 'x', 'y'], $at, $errors)) {
                continue;
            }
            $floor = $place['floor_id'] ?? null;
            if (!is_string($floor) || !isset($out['floors'][$floor])) {
                $errors[] = _s('%1$s.floor_id names no defined floor.', $at);
                continue;
            }
            $out['placements'][$apUid] = ['floor_id'=>$floor,
                'x'=>self::number($place['x'] ?? null, 0, 1, $at.'.x', $errors, false),
                'y'=>self::number($place['y'] ?? null, 0, 1, $at.'.y', $errors, false)];
        }
        foreach (self::list($document, 'ssids', self::MAX_SSIDS, $errors) as $i => $ssid) {
            $at = 'ssids['.$i.']';
            if (!self::fields($ssid, ['ssid', 'site', 'vlan', 'expect', 'floors', 'aps', 'bands'], $at, $errors)) {
                continue;
            }
            $name = self::text($ssid['ssid'] ?? null, 128, $at.'.ssid', $errors, false);
            $site = self::site($ssid['site'] ?? '', $at.'.site', $errors, true);
            $expect = $ssid['expect'] ?? 'site';
            if (!in_array($expect, ['site', 'floors', 'aps'], true)) {
                $errors[] = _s('%1$s.expect must be site, floors or aps.', $at);
                $expect = 'site';
            }
            $row = ['ssid'=>$name, 'ssid_uid'=>$name === null ? null : 'ssid-'.substr(hash('sha256', 'ssid:'.$name), 0, 24),
                'site'=>$site, 'vlan'=>self::int($ssid['vlan'] ?? null, 1, 4094, $at.'.vlan', $errors),
                'expect'=>$expect, 'floors'=>[], 'aps'=>[], 'bands'=>[]];
            foreach (self::strings($ssid['floors'] ?? [], $at.'.floors', $errors) as $floor) {
                if (!isset($out['floors'][$floor])) {
                    $errors[] = _s('%1$s.floors names an undefined floor "%2$s".', $at, $floor);
                }
                $row['floors'][] = $floor;
            }
            foreach (self::strings($ssid['aps'] ?? [], $at.'.aps', $errors) as $ap) {
                if (!WifiEnvelopeValidator::validApUid($ap)) {
                    $errors[] = _s('%1$s.aps lists AP IDs (ap-...).', $at);
                    continue;
                }
                $row['aps'][] = $ap;
            }
            foreach (self::strings($ssid['bands'] ?? [], $at.'.bands', $errors) as $band) {
                if (!in_array($band, self::BANDS, true)) {
                    $errors[] = _s('%1$s.bands may hold "2.4", "5" and "6".', $at);
                    continue;
                }
                $row['bands'][] = $band;
            }
            if ($expect === 'floors' && $row['floors'] === [] || $expect === 'aps' && $row['aps'] === []) {
                $errors[] = _s('%1$s expects %2$s but lists none.', $at, $expect);
            }
            foreach ($out['ssids'] as $other) {
                if ($other['ssid'] === $row['ssid'] && $other['site'] === $row['site']) {
                    $errors[] = _s('SSID "%1$s" is declared twice for the same site.', (string) $row['ssid']);
                }
            }
            $out['ssids'][] = $row;
        }
        foreach (self::list($document, 'events', self::MAX_EVENTS, $errors) as $i => $event) {
            $at = 'events['.$i.']';
            if (!self::fields($event, ['event_id', 'name', 'site', 'ssid', 'starts', 'ends', 'floors', 'min_aps',
                    'expected_clients', 'clients_per_ap'], $at, $errors)) {
                continue;
            }
            $row = ['event_id'=>self::id($event['event_id'] ?? null, $at.'.event_id', $errors),
                'name'=>self::text($event['name'] ?? null, 128, $at.'.name', $errors, false),
                'site'=>self::site($event['site'] ?? null, $at.'.site', $errors, false),
                'ssid'=>self::text($event['ssid'] ?? null, 128, $at.'.ssid', $errors, false),
                'starts'=>self::time($event['starts'] ?? null, $at.'.starts', $errors),
                'ends'=>self::time($event['ends'] ?? null, $at.'.ends', $errors),
                'floors'=>[],
                'min_aps'=>isset($event['min_aps']) ? self::int($event['min_aps'], 0, 100000, $at.'.min_aps', $errors) : null,
                'expected_clients'=>isset($event['expected_clients'])
                    ? self::int($event['expected_clients'], 0, 1000000, $at.'.expected_clients', $errors) : null,
                'clients_per_ap'=>isset($event['clients_per_ap'])
                    ? self::int($event['clients_per_ap'], 1, 1000, $at.'.clients_per_ap', $errors) : null];
            foreach (self::strings($event['floors'] ?? [], $at.'.floors', $errors) as $floor) {
                if (!isset($out['floors'][$floor])) {
                    $errors[] = _s('%1$s.floors names an undefined floor "%2$s".', $at, $floor);
                }
                $row['floors'][] = $floor;
            }
            if ($row['starts'] !== null && $row['ends'] !== null && strcmp($row['ends'], $row['starts']) <= 0) {
                $errors[] = _s('%1$s ends before it starts.', $at);
            }
            if ($row['expected_clients'] !== null && $row['clients_per_ap'] === null) {
                $errors[] = _s('%1$s.expected_clients needs clients_per_ap, the declared capacity of one AP.', $at);
            }
            $declared = array_filter($out['ssids'], static fn($s) => $s['ssid'] === $row['ssid']
                && ($s['site'] === '' || $s['site'] === $row['site']));
            if ($row['ssid'] !== null && !$declared) {
                $errors[] = _s('%1$s.ssid "%2$s" has no SSID intent (with its VLAN) for site "%3$s".', $at, $row['ssid'],
                    (string) $row['site']);
            }
            foreach ($out['events'] as $other) {
                if ($other['event_id'] === $row['event_id']) {
                    $errors[] = _s('Event "%1$s" is defined twice.', (string) $row['event_id']);
                }
            }
            $out['events'][] = $row;
        }
        foreach (self::list($document, 'known_bssids', self::MAX_KNOWN, $errors) as $i => $known) {
            $at = 'known_bssids['.$i.']';
            if (!self::fields($known, ['bssid', 'label'], $at, $errors)) {
                continue;
            }
            $bssid = is_string($known['bssid'] ?? null) ? strtolower($known['bssid']) : null;
            if ($bssid === null || !preg_match('/^[0-9a-f]{2}(:[0-9a-f]{2}){5}$/D', $bssid)) {
                $errors[] = _s('%1$s.bssid must be a MAC address like 00:00:5e:00:53:01.', $at);
                continue;
            }
            $out['known_bssids'][$bssid] = ['bssid'=>$bssid,
                'label'=>self::text($known['label'] ?? '', 128, $at.'.label', $errors, true)];
        }
        if ($errors) {
            throw new WifiConfigError(array_slice($errors, 0, 50));
        }
        $out['floors'] = array_values($out['floors']);
        $out['known_bssids'] = array_values($out['known_bssids']);
        ksort($out['placements']);
        if (strlen(json_encode($out)) > self::MAX_BYTES) {
            throw new WifiConfigError([_s('The configuration is larger than %1$s bytes.', self::MAX_BYTES)]);
        }
        $stored = strlen(json_encode(self::pack($out)));
        if ($stored > self::MAX_STORED_BYTES) {
            throw new WifiConfigError([_s('The configuration takes %1$s bytes once packed, more than the %2$s the module configuration can hold. Remove placements of APs that are gone, or split sites across fewer floors.',
                $stored, self::MAX_STORED_BYTES)]);
        }
        return $out;
    }

    /**
     * What is written to the module configuration. A document that fits is stored as it is (see stored()), so it stays readable in the
     * database. A larger one becomes one string: deflated JSON of everything but the placements, followed by the
     * placements as fixed 22-byte records (AP ID, floor index, x and y in units of 0.00001), base64-encoded.
     * @return array|string
     */
    public static function pack(array $config) {
        $document = self::stored($config);
        if (strlen(json_encode($document)) <= self::MAX_STORED_BYTES || !function_exists('gzdeflate')) {
            return $document;
        }
        $floors = array_flip(array_column($document['floors'], 'floor_id'));
        $records = '';
        foreach ($document['placements'] as $apUid => $place) {
            $records .= hex2bin(substr($apUid, 3)).pack('nNN', $floors[$place['floor_id']],
                (int) round($place['x'] * 100000), (int) round($place['y'] * 100000));
        }
        $json = json_encode(['placements'=>[]] + $document);
        return self::PACKED.base64_encode(gzdeflate(pack('N', strlen($json)).$json.$records, 9));
    }

    /**
     * A stored form back as a document, still to be validated with normalise().
     * @param array|string $stored
     * @throws WifiConfigError when a packed form is damaged
     */
    public static function unpack($stored) {
        if (!is_string($stored)) {
            return $stored;
        }
        $damaged = new WifiConfigError([_('The stored configuration is damaged and cannot be read.')]);
        if (strncmp($stored, self::PACKED, strlen(self::PACKED)) !== 0 || !function_exists('gzinflate')) {
            throw $damaged;
        }
        $raw = base64_decode(substr($stored, strlen(self::PACKED)), true);
        $raw = $raw !== false ? @gzinflate($raw, self::MAX_BYTES * 2) : false;
        if ($raw === false || strlen($raw) < 4) {
            throw $damaged;
        }
        $length = unpack('N', $raw)[1];
        $document = json_decode((string) substr($raw, 4, $length), true);
        $records = (string) substr($raw, 4 + $length);
        if (!is_array($document) || !is_array($document['floors'] ?? null) || strlen($records) % 22 !== 0) {
            throw $damaged;
        }
        $floors = array_column($document['floors'], 'floor_id');
        $document['placements'] = [];
        foreach (str_split($records, 22) as $record) {
            $place = unpack('nfloor/Nx/Ny', $record, 12);
            if (!isset($floors[$place['floor']])) {
                throw $damaged;
            }
            $document['placements']['ap-'.bin2hex(substr($record, 0, 12))] = ['floor_id'=>$floors[$place['floor']],
                'x'=>$place['x'] / 100000, 'y'=>$place['y'] / 100000];
        }
        return $document;
    }

    /**
     * The part of a valid document a viewer may see: floors, intent and events of the visible sites, placements of
     * the visible APs. Known BSSIDs are not site-bound and carry only a label.
     */
    public static function visible(array $config, array $sites, array $apUids): array {
        $sites = array_fill_keys($sites, true);
        $floors = array_values(array_filter($config['floors'], static fn($f) => isset($sites[$f['site']])));
        $floorIds = array_fill_keys(array_column($floors, 'floor_id'), true);
        return ['floors'=>$floors,
            'placements'=>array_filter(array_intersect_key($config['placements'], array_fill_keys($apUids, true)),
                static fn($p) => isset($floorIds[$p['floor_id']])),
            'ssids'=>array_values(array_filter($config['ssids'], static fn($s) => $s['site'] === '' || isset($sites[$s['site']]))),
            'events'=>array_values(array_filter($config['events'], static fn($e) => isset($sites[$e['site']]))),
            'known_bssids'=>array_column($config['known_bssids'], null, 'bssid')];
    }

    /**
     * The form a valid document is stored in: the editor's document as plain arrays, which normalise() accepts
     * again. The normalised form itself is not, as it carries derived fields such as each SSID's ID.
     */
    public static function stored(array $config): array {
        return json_decode(json_encode(self::export($config)), true);
    }

    /** The stored document as the editor shows it: the shape an operator writes, without derived fields. */
    public static function export(array $config): array {
        $ssids = array_map(static function ($s) {
            unset($s['ssid_uid']);
            return array_filter($s, static fn($v) => $v !== [] && $v !== '');
        }, $config['ssids']);
        return ['version'=>self::VERSION, 'floors'=>array_map(static fn($f) => array_filter($f,
                static fn($v) => $v !== null && $v !== ''), $config['floors']),
            'placements'=>(object) $config['placements'], 'ssids'=>$ssids,
            'events'=>array_map(static fn($e) => array_filter($e, static fn($v) => $v !== null && $v !== []),
                $config['events']),
            'known_bssids'=>$config['known_bssids']];
    }

    private static function list(array $document, string $key, int $max, array &$errors): array {
        $value = $document[$key] ?? [];
        if (!is_array($value) || $value !== [] && array_keys($value) !== range(0, count($value) - 1)) {
            $errors[] = _s('%1$s must be a list.', $key);
            return [];
        }
        if (count($value) > $max) {
            $errors[] = _s('At most %1$s entries in %2$s.', $max, $key);
            return [];
        }
        return $value;
    }

    private static function fields($value, array $allowed, string $at, array &$errors): bool {
        if (!is_array($value)) {
            $errors[] = _s('%1$s must be an object.', $at);
            return false;
        }
        foreach (array_diff(array_keys($value), $allowed) as $key) {
            $errors[] = _s('%1$s: unknown key "%2$s".', $at, (string) $key);
        }
        return true;
    }

    private static function id($value, string $at, array &$errors): ?string {
        if (!is_string($value) || !preg_match(self::ID, $value)) {
            $errors[] = _s('%1$s must be lower-case letters, digits, "-" or "_" (at most 64).', $at);
            return null;
        }
        return $value;
    }

    private static function site($value, string $at, array &$errors, bool $optional): string {
        if ($optional && $value === '') {
            return '';
        }
        if (!is_string($value) || !NetworkScope::validTagValue($value)) {
            $errors[] = _s('%1$s must be a site tag value.', $at);
            return '';
        }
        return $value;
    }

    private static function text($value, int $max, string $at, array &$errors, bool $optional): ?string {
        if (!is_string($value) || (!$optional && trim($value) === '') || strlen($value) > $max
                || preg_match('/[\x00-\x1f\x7f]/', $value)) {
            $errors[] = _s('%1$s must be text of at most %2$s characters.', $at, $max);
            return null;
        }
        return $value;
    }

    private static function int($value, int $min, int $max, string $at, array &$errors): ?int {
        if (!is_int($value) || $value < $min || $value > $max) {
            $errors[] = _s('%1$s must be a whole number from %2$s to %3$s.', $at, $min, $max);
            return null;
        }
        return $value;
    }

    private static function number($value, float $min, float $max, string $at, array &$errors, bool $nullable): ?float {
        if ($value === null && $nullable) {
            return null;
        }
        if (!is_int($value) && !is_float($value) || $value < $min || $value > $max) {
            $errors[] = _s('%1$s must be a number from %2$s to %3$s.', $at, $min, $max);
            return null;
        }
        return round((float) $value, 5);
    }

    private static function strings($value, string $at, array &$errors): array {
        if (!is_array($value) || array_filter($value, static fn($v) => !is_string($v))) {
            $errors[] = _s('%1$s must be a list of text values.', $at);
            return [];
        }
        return array_values(array_unique($value));
    }

    private static function time($value, string $at, array &$errors): ?string {
        // Field by field, so an impossible date such as 30 February is refused rather than rolled forward.
        if (!is_string($value) || !preg_match('/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d))?Z$/D', $value, $m)
                || !checkdate((int) $m[2], (int) $m[3], (int) $m[1])
                || (int) $m[4] > 23 || (int) $m[5] > 59 || (int) ($m[6] ?? 0) > 59 || strtotime($value) === false) {
            $errors[] = _s('%1$s must be a UTC time like 2026-11-02T08:00:00Z.', $at);
            return null;
        }
        return gmdate('Y-m-d\TH:i:s\Z', strtotime($value));
    }
}
