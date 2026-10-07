'use strict';
// Runs a native-template normaliser exactly as Zabbix would: the composed
// preprocessing script (templates/source) receives walk[] text as `value`.
//
//   node tests/js/run_normaliser.cjs <raw_key> <file.snmprec|file.walk> [--walk-only]
//
// A .snmprec file is first rendered the way Zabbix prints walk[] output, so
// captured device walks and synthetic fixtures can be replayed directly.

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const SOURCE = path.join(ROOT, 'templates', 'source');

global.sha256 = (text) => crypto.createHash('sha256').update(String(text), 'utf8').digest('hex');

function datasetFor(rawKey) {
  const manifest = JSON.parse(fs.readFileSync(path.join(SOURCE, 'datasets.json'), 'utf8'));
  const entry = manifest.datasets.find((d) => d.raw_key === rawKey);
  if (!entry) throw new Error(`unknown raw key ${rawKey}`);
  return entry;
}

// Same composition as templates/generate_snmp.py.
function compose(entry) {
  const read = (name) => fs.readFileSync(path.join(SOURCE, 'js', name), 'utf8');
  return [read('lib.js'), read(entry.script),
    `return JSON.stringify(NE.run('${entry.dataset}', '${entry.adapter}', value, function (w, e) { return ${entry.call}; }));`,
  ].join('\n');
}

function oidKey(oid) {
  return oid.split('.').map(Number);
}

function compareOid(a, b) {
  const x = oidKey(a), y = oidKey(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}

function quote(text) {
  return '"' + text.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
}

// net-snmp prints 16 octets per line; Zabbix passes the wrapped text through.
function hexString(buffer) {
  const pairs = [...buffer].map((b) => b.toString(16).toUpperCase().padStart(2, '0'));
  const lines = [];
  for (let i = 0; i < pairs.length; i += 16) lines.push(pairs.slice(i, i + 16).join(' '));
  return lines.join(' \n');
}

// Mirrors checks_snmp.c: octet strings become quoted STRING values when they are
// printable ASCII, contain no NUL and are not exactly six octets long.
function renderOctets(buffer) {
  const printable = buffer.length !== 6 && [...buffer].every((b) => b >= 0x20 && b <= 0x7e);
  if (buffer.length === 0) return '""';
  return printable ? 'STRING: ' + quote(buffer.toString('latin1')) : 'Hex-STRING: ' + hexString(buffer);
}

function renderValue(tag, value) {
  switch (tag) {
    case '2': return 'INTEGER: ' + value;
    case '4': return renderOctets(Buffer.from(value, 'utf8'));
    case '4x': return renderOctets(Buffer.from(value, 'hex'));
    case '5': return '""';
    case '6': return 'OID: .' + value.replace(/^\./, '');
    case '64': return 'IpAddress: ' + value;
    case '65': return 'Counter32: ' + value;
    case '66': return 'Gauge32: ' + value;
    case '67': return 'Timeticks: ' + value;
    case '70': return 'Counter64: ' + value;
    default: throw new Error(`unsupported snmprec tag ${tag}`);
  }
}

function walkText(snmprec, roots) {
  const rows = snmprec.split('\n').filter(Boolean).map((line) => {
    const first = line.indexOf('|'), second = line.indexOf('|', first + 1);
    return [line.slice(0, first), line.slice(first + 1, second), line.slice(second + 1)];
  });
  const out = [];
  for (const root of roots) {
    const selected = rows.filter(([oid]) => oid === root || oid.startsWith(root + '.'))
      .sort((a, b) => compareOid(a[0], b[0]));
    for (const [oid, tag, value] of selected) out.push(`.${oid} = ${renderValue(tag, value)}`);
  }
  return out.join('\n');
}

function run(rawKey, file) {
  const entry = datasetFor(rawKey);
  const text = fs.readFileSync(file, 'utf8');
  const value = file.endsWith('.snmprec') ? walkText(text, entry.walk) : text;
  // eslint-disable-next-line no-new-func
  return { value, output: new Function('value', compose(entry))(value) };
}

module.exports = { compose, datasetFor, walkText, run };

if (require.main === module) {
  const [rawKey, file, flag] = process.argv.slice(2);
  const { value, output } = run(rawKey, file);
  process.stdout.write(flag === '--walk-only' ? value + '\n' : output + '\n');
}
