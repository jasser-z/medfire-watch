import fs from 'node:fs';import vm from 'node:vm';
for(const name of ['live_camera','video_player']){const html=fs.readFileSync(new URL('../dashboard/'+name+'.html',import.meta.url),'utf8');for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))new vm.SourceTextModule(match[1]);console.log(name,'script syntax passed')}
