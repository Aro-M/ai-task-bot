import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { scriptHashes } from './csp.mjs';

test('CSP hashes only exact inline scripts, excludes external scripts and deduplicates', () => {
  const payload = 'self.__next_f.push([1,"hydration"])';
  const expected = `'sha256-${createHash('sha256').update(payload).digest('base64')}'`;
  assert.equal(
    scriptHashes(
      `<script src="/_next/a.js"></script><script>${payload}</script><script>${payload}</script>`,
    ),
    expected,
  );
  assert.notEqual(scriptHashes(`<script>${payload} </script>`), expected);
  assert.equal(scriptHashes('<p>untrusted text</p>'), '');
});
