/**
 * Who gets which installer.
 *
 * The agent strings are real, copied from what these clients actually send.
 * The PowerShell ones are the reason this file exists: they open with
 * `Mozilla/5.0`, so a browser check written first hands every Windows install
 * an HTML page.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { wantedBy } from './index.js';

const ask = (agent, extra = {}, url = 'https://get.comodor.ai/') =>
  wantedBy(new Request(url, { headers: { 'user-agent': agent, ...extra } }));

test('PowerShell gets the PowerShell script, despite saying Mozilla', () => {
  const agents = [
    'Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.26100; en-US) PowerShell/7.4.6',
    'Mozilla/5.0 (Windows NT; Windows NT 10.0; en-US) WindowsPowerShell/5.1.26100.2161',
    'Mozilla/5.0 (Windows NT 10.0; Microsoft Windows 10.0.22631; en-GB) PowerShell/7.5.0',
  ];
  for (const agent of agents) assert.equal(ask(agent), 'ps1', agent);
});

test('curl and wget get the shell script', () => {
  for (const agent of [
    'curl/8.9.1',
    'curl/7.68.0',
    'Wget/1.21.4',
    'HTTPie/3.2.2',
  ]) {
    assert.equal(ask(agent), 'sh', agent);
  }
});

test('a browser is sent to the page', () => {
  const chrome =
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36';
  assert.equal(ask(chrome, { 'sec-fetch-mode': 'navigate' }), 'browser');
  assert.equal(ask(chrome), 'browser');
  assert.equal(
    ask('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15'),
    'browser',
  );
});

test('a navigation from something calling itself PowerShell is still PowerShell', () => {
  // Order matters more than the header does.
  assert.equal(
    ask('Mozilla/5.0 (Windows NT 10.0; en-US) PowerShell/7.4.6', { 'sec-fetch-mode': 'navigate' }),
    'ps1',
  );
});

test('an unrecognised client gets the shell script, not an HTML page', () => {
  assert.equal(ask(''), 'sh');
  assert.equal(ask('something-nobody-has-heard-of/1.0'), 'sh');
});

test('an explicit ask beats the guess', () => {
  const chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0';
  assert.equal(ask(chrome, {}, 'https://get.comodor.ai/?ps1'), 'ps1');
  assert.equal(ask(chrome, {}, 'https://get.comodor.ai/?sh'), 'sh');
  assert.equal(ask('curl/8.9.1', {}, 'https://get.comodor.ai/?windows'), 'ps1');
});
