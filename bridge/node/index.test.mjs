// Attacks on the wrapper: every way themis can answer, and every way it can fail to.
// A stand-in program plays themis, so these tests need nothing installed but Node.

import assert from 'node:assert/strict';
import { chmodSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

import { themisCheck } from './index.mjs';

const folder = mkdtempSync(join(tmpdir(), 'themis-bridge-'));

/** A stand-in for themis: a script that prints `stdout`, then exits with `code`. */
function standIn(name, { stdout = '', stderr = '', code = 0, body = '' }) {
  const path = join(folder, `${name}.mjs`);
  const script = body || `process.stdout.write(${JSON.stringify(stdout)}); process.stderr.write(${JSON.stringify(stderr)}); process.exit(${code});`;
  writeFileSync(path, `#!/usr/bin/env node\n${script}\n`);
  chmodSync(path, 0o755);
  return [process.execPath, path];
}

const report = (verdict, results = []) => JSON.stringify({ themis_report: 1, verdict, exit_code: { pass: 0, fail: 1, refuse: 2 }[verdict], results });
const ran = { rule: 'ext/docs', level: 'enforce', status: 'ran', verdict: 'pass', findings: [] };
const broken = { rule: 'config/locked', level: 'enforce', status: 'ran', verdict: 'fail', findings: [] };

test('a pass is a pass, and says how much ran', () => {
  const outcome = themisCheck({ command: standIn('pass', { stdout: report('pass', [ran]), code: 0 }) });
  assert.deepEqual([outcome.verdict, outcome.exitCode, outcome.reason], ['pass', 0, '1 rule(s) ran']);
});

test('a fail names the rule that failed', () => {
  const outcome = themisCheck({ command: standIn('fail', { stdout: report('fail', [ran, broken]), code: 1 }) });
  assert.deepEqual([outcome.verdict, outcome.exitCode, outcome.reason], ['fail', 1, 'config/locked: fail']);
});

test('a refuse stays a refuse, and is not folded into fail', () => {
  const undecided = { ...broken, rule: 'order/sealed-first', verdict: 'refuse' };
  const outcome = themisCheck({ command: standIn('refuse', { stdout: report('refuse', [undecided]), code: 2 }) });
  assert.deepEqual([outcome.verdict, outcome.exitCode], ['refuse', 2]);
});

test('themis refusing with no report passes its reason on', () => {
  const outcome = themisCheck({ command: standIn('nothing', { stderr: 'themis: there is no themis.toml here.', code: 2 }) });
  assert.equal(outcome.verdict, 'refuse');
  assert.match(outcome.reason, /no themis\.toml/);
});

for (const [name, standin, said] of [
  ['a program that is not installed', ['no-such-program-anywhere'], /could not be started/],
  ['an exit code that is not a verdict', standIn('odd', { stdout: report('pass'), code: 7 }), /not one of its verdicts/],
  ['output that is not a report', standIn('garbage', { stdout: 'all good!', code: 0 }), /did not print a report/],
  ['a report that disagrees with the exit code', standIn('liar', { stdout: report('fail', [broken]), code: 0 }), /disagree/],
  ['a report with no results', standIn('hollow', { stdout: JSON.stringify({ verdict: 'pass' }), code: 0 }), /disagree/],
  ['a program that never finishes', standIn('slow', { body: 'setTimeout(() => {}, 60000);' }), /did not finish in time/],
]) {
  test(`${name} is a refuse, never a pass`, () => {
    const outcome = themisCheck({ command: standin, timeoutMs: 1500 });
    assert.equal(outcome.verdict, 'refuse');
    assert.equal(outcome.exitCode, 2);
    assert.match(outcome.reason, said);
  });
}

test('the rules asked for and the changed flag reach themis', () => {
  const echo = standIn('echo', { body: `process.stdout.write(JSON.stringify({ verdict: 'pass', results: [{ rule: process.argv.slice(2).join(' '), status: 'ran' }] }));` });
  const outcome = themisCheck({ command: echo, rules: ['order/sealed-first'], changed: true });
  assert.equal(outcome.results[0].rule, 'check order/sealed-first --reporter json --changed');
});
