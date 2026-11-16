#!/usr/bin/env node
// `themis-check`: run Themis from a JavaScript project's scripts, and exit with its verdict.
//
//   themis-check                       run `themis check` in this folder
//   themis-check -- uv run themis      start themis another way

import { themisCheck } from './index.mjs';

const split = process.argv.indexOf('--');
const command = split === -1 ? ['themis'] : process.argv.slice(split + 1);
const outcome = themisCheck({ command });
const stream = outcome.verdict === 'pass' ? process.stdout : process.stderr;
stream.write(`themis: ${outcome.verdict.toUpperCase()} - ${outcome.reason}\n`);
process.exit(outcome.exitCode);
