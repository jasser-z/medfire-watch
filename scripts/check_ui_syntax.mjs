import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
for (const name of fs.readdirSync(new URL('../dashboard/', import.meta.url)).filter((name) => name.endsWith('.mjs'))) {
  const source = fs.readFileSync(new URL('../dashboard/' + name, import.meta.url), 'utf8');
  const result = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: source, encoding: 'utf8' });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    process.stderr.write(result.stderr);
    process.exit(result.status || 1);
  }
  console.log(name, 'script syntax passed');
}
