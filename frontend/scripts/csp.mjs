import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export function scriptHashes(html) {
  const hashes = new Set();
  for (const match of html.matchAll(
    /<script\b([^>]*)>([\s\S]*?)<\/script>/gi,
  )) {
    if (!/\bsrc\s*=/.test(match[1]) && match[2]) {
      hashes.add(
        `'sha256-${createHash('sha256').update(match[2]).digest('base64')}'`,
      );
    }
  }
  return [...hashes].join(' ');
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const hashes = scriptHashes(readFileSync('out/index.html', 'utf8'));
  if (!hashes)
    throw new Error(
      'Next export has no hydration scripts; check CSP generation.',
    );
  writeFileSync(
    'nginx.generated.conf',
    readFileSync('nginx.conf', 'utf8').replace(
      '__NEXT_SCRIPT_HASHES__',
      hashes,
    ),
  );
}
