import fs from 'node:fs';
import vm from 'node:vm';
for (const name of ['live_camera', 'video_player']) {
  const source = fs.readFileSync(new URL('../dashboard/' + name + '.mjs', import.meta.url), 'utf8');
  new vm.SourceTextModule(source);
  console.log(name, 'script syntax passed');
}
