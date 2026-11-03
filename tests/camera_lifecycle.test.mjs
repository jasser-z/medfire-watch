import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';
import { parseHTML } from 'linkedom';

const flush = () => new Promise((resolve) => setImmediate(resolve));

test('camera restart ignores a previous capture request and stops all tracks on page exit', async () => {
  const { document } = parseHTML(fs.readFileSync(new URL('../dashboard/live_camera.html', import.meta.url), 'utf8'));
  const context2d = new Proxy({}, { get: () => () => {} });
  const nativeCreate = document.createElement.bind(document);
  document.createElement = (name) => {
    const element = nativeCreate(name);
    if (name === 'canvas') {
      element.getContext = () => context2d;
      element.toBlob = (callback) => callback(new Blob(['frame']));
    }
    return element;
  };
  const video = document.querySelector('#video');
  document.querySelector('#overlay').getContext = () => context2d;
  video.play = async () => {};
  video.readyState = 2;
  video.videoWidth = 1280;
  video.videoHeight = 720;
  video.getBoundingClientRect = () => ({ width: 1280, height: 720 });
  video.requestVideoFrameCallback = () => 1;
  let stopped = 0;
  const tracks = [];
  const pending = [];
  const events = {};
  const timers = [];
  const sandbox = {
    document,
    crypto: webcrypto,
    Blob,
    FormData,
    AbortSignal,
    URLSearchParams,
    location: { search: '' },
    performance: { now: () => 1000 },
    devicePixelRatio: 1,
    requestAnimationFrame: () => 1,
    setTimeout: (callback) => timers.push(callback),
    sourceDetections: (data) => data.detections,
    navigator: {
      mediaDevices: {
        getUserMedia: async () => {
          const track = { stop: () => stopped++, getSettings: () => ({ width: 1280, height: 720 }) };
          tracks.push(track);
          return { getTracks: () => [track], getVideoTracks: () => [track] };
        },
      },
    },
    window: {
      addEventListener: (name, callback) => {
        events[name] = callback;
      },
    },
    fetch: async (url) => {
      if (url === '/live-camera/detect') return new Promise((resolve) => pending.push(resolve));
      return { ok: true, json: async () => ({ minutes: 5, delivered: 0, failed: 0 }) };
    },
  };
  const source = fs.readFileSync(new URL('../dashboard/live_camera.mjs', import.meta.url), 'utf8');
  vm.runInNewContext(source.replace(/^import[^\n]+\n/, ''), sandbox);
  await flush();
  const start = document.querySelector('#start');
  await start.onclick();
  await flush();
  assert.equal(pending.length, 1);
  await start.onclick();
  assert.equal(stopped, 1);
  await start.onclick();
  await flush();
  assert.equal(tracks.length, 2);
  assert.equal(pending.length, 1); // Capture scheduling throttles the rapid restart.
  pending[0]({ ok: true, json: async () => ({ detections: [{ class: 'fire' }], updates_per_second: 7 }) });
  await flush();
  assert.equal(document.querySelector('#detect').textContent, 'Detection waiting');
  events.pagehide();
  assert.equal(stopped, 2);
  assert.equal(video.srcObject, null);
});
