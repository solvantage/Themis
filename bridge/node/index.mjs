// A thin wrapper so a JavaScript check runner can hold Themis as one of its checks.
//
// The contract is Themis's own: `themis check --reporter=json` prints one JSON report, and exits
// 0 for PASS, 1 for FAIL and 2 for REFUSE. This wrapper keeps REFUSE distinct from FAIL, and
// turns anything it cannot read into a REFUSE: a missing program, a crash, a timeout, output
// that is not the report. A check that could not decide is never reported as a pass.

import { spawnSync } from 'node:child_process';

const VERDICT_BY_EXIT = { 0: 'pass', 1: 'fail', 2: 'refuse' };
const EXIT_BY_VERDICT = { pass: 0, fail: 1, refuse: 2 };

function refuse(reason) {
  return { verdict: 'refuse', exitCode: 2, reason, results: [] };
}

/**
 * Run `themis check` and return its verdict.
 *
 * @param {object} [options]
 * @param {string} [options.cwd] the repository to check (default: the current folder)
 * @param {string[]} [options.command] how to start themis (default: ['themis'])
 * @param {string[]} [options.rules] only these rule ids
 * @param {boolean} [options.changed] skip external checks whose paths did not change
 * @param {number} [options.timeoutMs] stop waiting after this long (default: ten minutes)
 * @returns {{verdict: 'pass'|'fail'|'refuse', exitCode: number, reason: string, results: object[]}}
 */
export function themisCheck(options = {}) {
  const { cwd = process.cwd(), command = ['themis'], rules = [], changed = false, timeoutMs = 600_000 } = options;
  const args = [...command.slice(1), 'check', ...rules, '--reporter', 'json', ...(changed ? ['--changed'] : [])];
  const done = spawnSync(command[0], args, { cwd, encoding: 'utf8', timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 });

  if (done.error) {
    const why = done.error.code === 'ETIMEDOUT' ? 'did not finish in time' : `could not be started (${done.error.code})`;
    return refuse(`themis ${why}`);
  }
  if (done.signal) return refuse(`themis was stopped by ${done.signal}`);
  const expected = VERDICT_BY_EXIT[done.status];
  if (expected === undefined) return refuse(`themis exited ${done.status}, which is not one of its verdicts`);

  let report;
  try {
    report = JSON.parse(done.stdout);
  } catch {
    // Exit 2 with no report is themis saying why on standard error: there was nothing to check.
    if (expected === 'refuse') return refuse((done.stderr || '').trim() || 'themis refused and gave no report');
    return refuse('themis did not print a report that can be read');
  }
  if (report === null || typeof report !== 'object' || report.verdict !== expected || !Array.isArray(report.results)) {
    return refuse('the report and the exit code disagree, so neither is trusted');
  }
  const failing = report.results.filter((result) => result.level === 'enforce' && result.verdict && result.verdict !== 'pass');
  const reason = failing.length
    ? failing.map((result) => `${result.rule}: ${result.verdict}`).join('; ')
    : `${report.results.filter((result) => result.status === 'ran').length} rule(s) ran`;
  return { verdict: expected, exitCode: EXIT_BY_VERDICT[expected], reason, results: report.results };
}
