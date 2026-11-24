"""The walk parser and octet helpers in templates/source/js/lib.js, run in Duktape (Zabbix's JavaScript engine).

2.3.1 rewrote them for speed: a Dell N4064's VLAN walk took over Zabbix's 10-second script limit. These tests hold the
rewritten helpers to the 2.3.0 implementations, kept below verbatim, on edge cases and random input.
"""
from __future__ import annotations

import json
from pathlib import Path
import random

import pytest

dukpy = pytest.importorskip("dukpy")

ROOT = Path(__file__).resolve().parents[2]
LIB = (ROOT / "templates/source/js/lib.js").read_text(encoding="utf-8")

# The 2.3.0 implementations.
REFERENCE = r"""
var OLD = {};
OLD.parseWalk = function (text) {
    var rows = {}, order = [], pos = 0, len = text.length;
    var head = /^\.?([0-9]+(?:\.[0-9]+)*) = (?:([A-Za-z0-9-]+): ?)?/;
    while (pos < len) {
        var eol = text.indexOf('\n', pos);
        if (eol < 0) { eol = len; }
        var line = text.substring(pos, eol);
        var m = head.exec(line);
        if (!m) { pos = eol + 1; continue; }
        var oid = m[1], type = m[2] || 'STRING', start = pos + m[0].length, value;
        if (text.charAt(start) === '"') {
            var i = start + 1, out = '';
            while (i < len && text.charAt(i) !== '"') {
                if (text.charAt(i) === '\\' && i + 1 < len) { i++; }
                out += text.charAt(i);
                i++;
            }
            value = out;
            eol = text.indexOf('\n', i);
            if (eol < 0) { eol = len; }
        }
        else {
            value = text.substring(start, eol);
            while (eol < len) {
                var next = text.indexOf('\n', eol + 1);
                if (next < 0) { next = len; }
                var more = text.substring(eol + 1, next);
                if (more === '' || head.test(more)) { break; }
                value += ' ' + more;
                eol = next;
            }
            value = value.replace(/\s+$/, '');
        }
        if (/^No (Such|more) /.test(value)) { type = 'MISSING'; }
        if (!rows.hasOwnProperty(oid)) { order.push(oid); }
        rows[oid] = {type: type, value: value};
        pos = eol + 1;
    }
    return {rows: rows, order: order};
};
OLD.hex = function (v) {
    var out = [], parts = v.split(/\s+/), i;
    for (i = 0; i < parts.length; i++) {
        if (!/^[0-9A-Fa-f]{2}$/.test(parts[i])) { break; }
        out.push(parseInt(parts[i], 16));
    }
    return out;
};
OLD.bitsSet = function (bytes, offset) {
    var out = [], i, b;
    if (!bytes) { return out; }
    for (i = 0; i < bytes.length; i++) {
        for (b = 0; b < 8; b++) {
            if (bytes[i] & (0x80 >> b)) { out.push(i * 8 + b + (offset || 0)); }
        }
    }
    return out;
};
"""

COMPARE = r"""
(function (cases, walks) {
    var bad = [];
    for (var i = 0; i < cases.length; i++) {
        var v = cases[i], entry = {type: 'Hex-STRING', value: v};
        if (JSON.stringify(NE.hexOctets(v)) !== JSON.stringify(OLD.hex(v))) { bad.push(['hexOctets', v]); }
        if (JSON.stringify(NE.bytes(entry)) !== JSON.stringify(OLD.hex(v))) { bad.push(['bytes', v]); }
        if (JSON.stringify(NE.hexBits(entry, 1)) !== JSON.stringify(OLD.bitsSet(OLD.hex(v), 1))) { bad.push(['hexBits', v]); }
        if (JSON.stringify(NE.bitsSet(OLD.hex(v), 0)) !== JSON.stringify(OLD.bitsSet(OLD.hex(v), 0))) { bad.push(['bitsSet', v]); }
    }
    for (i = 0; i < walks.length; i++) {
        if (JSON.stringify(NE.parseWalk(walks[i])) !== JSON.stringify(OLD.parseWalk(walks[i]))) { bad.push(['parseWalk', walks[i]]); }
    }
    return JSON.stringify(bad);
})(dukpy['cases'], dukpy['walks'])
"""

HEX_CASES = [
    "", " ", "00", "0F", "ff", "Ff 0a", "00 0F C1 FF C0 AB 00 00", " 00 0F", "00  0F", "00 0F \n00 FF",
    "00\t0F", "00 0F", "0F0", "0F 0", "0F G0", "0G", "00 0F \n", "00 00 00 00", "80", "80 01 00 00 \n00 00",
    "FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF FF", "0f 0a", "00 　 0F", "00 0F 1", "00 0F\\",
]

WALK_CASES = [
    '.1.3.6.1.2.1.1.5.0 = STRING: "sw-01"\n.1.3.6.1.2.1.1.3.0 = 42199904\n',
    '.1.3.6.1.2.1.1.1.0 = STRING: "a \\"quoted\\" name"\n.1.2 = INTEGER: 1\n',
    '.1.3.6.1.2.1.1.1.0 = STRING: "ends in a backslash\\"\n.1.2 = STRING: "next"\n.1.3 = INTEGER: 3\n',
    '.1.3.6.1.2.1.1.1.0 = STRING: "unterminated\n.1.2 = INTEGER: 1\n',
    '.1.3.6.1.2.1.1.1.0 = STRING: "trailing backslash at the end\\',
    '.1.3.6.1.2.1.1.1.0 = STRING: "two\nlines"\n.1.2 = INTEGER: 1',
    '.1.3.6.1.2.1.17.7.1.4.3.1.2.1 = Hex-STRING: 00 0F C1 FF C0 AB C0 00 00 00 00 00 00 00 00 00 \n'
    '00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 \n00 00 \n.1.3.6.1.2.1.17.7.1.4.3.1.2.2 = Hex-STRING: FF \n',
    '.1.3.6.1.2.1.2.2.1.2.1 = STRING: "Port é1 – uplink"\n.1.3.6.1.2.1.2.2.1.2.2 = STRING: ""\n',
    '.1.3.6.1.2.1.1.1.0 = No Such Object available on this agent at this OID\n',
    '1.3.6.1.2.1.1.1.0 = STRING: "no leading dot"\r\n.1.2 = Hex-STRING: 0A 0B  \t\n',
    '.1.2 = Hex-STRING: 00 01 \n  \n.1.3 = INTEGER: 5\n',
    '.1.2 = Hex-STRING: 00 01 \nnot a = continuation\n.1.3 = INTEGER: 5\n',
    'garbage line\n.1.2 = Gauge32: 7\n\n\n.1.4 = Counter64: 9',
]


def compare(hex_cases, walk_cases):
    """Every input where a rewritten helper and its 2.3.0 original disagree."""
    return json.loads(dukpy.evaljs(LIB + "\n" + REFERENCE + "\n" + COMPARE, cases=hex_cases, walks=walk_cases))


def test_rewritten_helpers_match_the_2_3_0_ones_on_edge_cases():
    assert compare(HEX_CASES, WALK_CASES) == []


def test_rewritten_helpers_match_the_2_3_0_ones_on_random_input():
    rng = random.Random(20261124)
    alphabet = list("0000000FFfa19 \n\t") + [" ", "G", "\\", '"', "é", " = ", ".1.3.6.1.2.1.1.1.0 = STRING: \"",
                                                 "\n.1.2 = Hex-STRING: ", "\n.1.3 = INTEGER: 4"]
    hex_cases = ["".join(rng.choice(alphabet[:16]) for _ in range(rng.randrange(0, 60))) for _ in range(1500)]
    walks = ["".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 80))) for _ in range(1500)]
    assert compare(hex_cases, walks) == []
