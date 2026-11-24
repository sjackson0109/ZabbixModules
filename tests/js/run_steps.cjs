'use strict';
// Runs an item's preprocessing steps as Zabbix does, for the step types the native templates use.
//
//   node tests/js/run_steps.cjs < {"steps": [...], "value": "..."}
//
// Prints {"value": "..."} when the value would be kept, or {"discarded": true} when a step discards it. A
// "Discard unchanged with heartbeat" step needs the previous value, so it is reported, not applied: {"throttle":
// "<heartbeat>"} is added to the result.

const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let value = input.value;
const result = {};
for (const step of input.steps) {
  if (step.type === 'JAVASCRIPT') {
    try {
      // eslint-disable-next-line no-new-func
      value = String(new Function('value', step.parameters[0])(value));
    }
    catch (error) {
      result.error = String(error);
      break;
    }
  }
  else if (step.type === 'NOT_MATCHES_REGEX') {
    if (new RegExp(step.parameters[0]).test(value)) {
      if (step.error_handler === 'DISCARD_VALUE') { result.discarded = true; break; }
      result.error = 'matched';
      break;
    }
  }
  else if (step.type === 'DISCARD_UNCHANGED_HEARTBEAT') {
    result.throttle = step.parameters[0];
  }
  else {
    throw new Error(`unsupported step ${step.type}`);
  }
}
if (!result.discarded && !result.error) { result.value = value; }
process.stdout.write(JSON.stringify(result) + '\n');
