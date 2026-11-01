import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseHTML } from 'linkedom';

test('camera fullscreen stage owns native video and overlay', () => {
  const source = fs.readFileSync(new URL('../dashboard/live_camera.html', import.meta.url), 'utf8');
  const { document } = parseHTML(source);
  const stage = document.querySelector('.stage');
  assert.ok(stage.querySelector('video'));
  assert.ok(stage.querySelector('canvas'));
  const controller = fs.readFileSync(new URL('../dashboard/live_camera.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes('/live-camera/app.mjs'));
  assert.ok(controller.includes('cameraStage.append(cameraHud)'));
  assert.ok(controller.includes('cameraStage.requestFullscreen()'));
  assert.ok(controller.includes('document.exitFullscreen()'));
});
test('video fullscreen stage owns original player and overlay', () => {
  const source = fs.readFileSync(new URL('../dashboard/video_player.html', import.meta.url), 'utf8');
  const { document } = parseHTML(source);
  const stage = document.querySelector('#stage');
  assert.ok(stage.querySelector('video'));
  assert.ok(stage.querySelector('canvas'));
  assert.ok(stage.querySelector('#controls'));
  const controller = fs.readFileSync(new URL('../dashboard/video_player.mjs', import.meta.url), 'utf8');
  assert.ok(source.includes('/video-test/app.mjs'));
  assert.ok(controller.includes('stage.requestFullscreen()'));
});
