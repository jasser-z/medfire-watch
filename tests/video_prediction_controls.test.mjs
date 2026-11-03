import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { parseHTML } from 'linkedom';

const flush = () => new Promise((resolve) => setImmediate(resolve));
function studio({ restore = false } = {}) {
  const { document } = parseHTML(fs.readFileSync(new URL('../dashboard/video_player.html', import.meta.url), 'utf8'));
  const video = document.querySelector('#v');
  let plays = 0,
    pauses = 0,
    fail = false;
  video.play = async () => {
    plays++;
  };
  video.pause = () => {
    pauses++;
  };
  video.requestVideoFrameCallback = () => 1;
  document.querySelector('#c').getContext = () => new Proxy({}, { get: () => () => {} });
  const calls = [],
    timers = [],
    intervals = [];
  const state = { status: 'processing', frames_processed: 8, fraction: 0.2 };
  const savedId = 'a'.repeat(32);
  const deletedKeys = [];
  let clock = 1000;
  const sandbox = {
    document,
    URLSearchParams,
    AbortSignal,
    URL,
    performance,
    sessionStorage: {
      getItem: () => (restore ? JSON.stringify({ id: savedId, fps: 10 }) : null),
      setItem: () => {},
      removeItem: (key) => deletedKeys.push(key),
    },
    Date: class extends Date {
      static now() {
        return clock;
      }
    },
    location: { search: '' },
    window: { addEventListener: () => {}, devicePixelRatio: 1 },
    playbackGate: () => 'play',
    contiguousFrontier: () => 10,
    setTimeout: (callback) => timers.push(callback),
    setInterval: (callback) => intervals.push(callback),
    fetch: async (url, options = {}) => {
      calls.push([url, options.method || 'GET']);
      if (options.method === 'POST') {
        if (fail) return { ok: false, json: async () => ({ detail: 'Session expired; sign in again.' }) };
        if (url.endsWith('/pause')) state.paused = true;
        if (url.endsWith('/resume')) state.paused = false;
        if (url.endsWith('/cancel')) state.status = 'cancelled';
        return { ok: true, json: async () => ({ paused: !!state.paused }) };
      }
      return { ok: true, json: async () => (url.includes('/frames?') ? { frames: [] } : { ...state }) };
    },
  };
  const source = fs.readFileSync(new URL('../dashboard/video_player.mjs', import.meta.url), 'utf8');
  vm.runInNewContext(
    source.replace(/^import[^\n]+\n/, '').replaceAll('JOB', restore ? 'local' : 'test-video'),
    sandbox,
  );
  return {
    advance: () => {
      clock += 1000;
    },
    document,
    deletedKeys,
    calls,
    timers,
    intervals,
    counts: () => ({ plays, pauses }),
    fail: () => {
      fail = true;
    },
  };
}

test('prediction buttons pause and resume computation, then cancel the job', async () => {
  const page = studio();
  await flush();
  const pause = page.document.querySelector('#prediction-pause');
  const cancel = page.document.querySelector('#prediction-cancel');
  assert.equal(pause.disabled, false);
  await pause.onclick();
  assert.deepEqual(page.calls.at(-1), ['/video-jobs/test-video/pause', 'POST']);
  assert.equal(pause.textContent, 'Resume prediction');
  assert.match(page.document.querySelector('#prediction-help').textContent, /Progress is kept/);
  for (const tick of page.intervals) tick();
  assert.equal(page.counts().plays, 0);
  await pause.onclick();
  assert.deepEqual(page.calls.at(-1), ['/video-jobs/test-video/resume', 'POST']);
  assert.equal(pause.textContent, 'Pause prediction');
  assert.equal(page.counts().plays, 1);
  await cancel.onclick();
  assert.deepEqual(page.calls.at(-1), ['/video-jobs/test-video/cancel', 'POST']);
  assert.equal(cancel.disabled, true);
  page.advance();
  page.timers.at(-1)();
  await flush();
  assert.equal(pause.disabled, true);
  assert.match(page.document.querySelector('#status').textContent, /cancelled/);
});

test('a rejected pause shows the server error and leaves controls usable', async () => {
  const page = studio();
  await flush();
  page.fail();
  const pause = page.document.querySelector('#prediction-pause');
  await pause.onclick();
  assert.equal(pause.disabled, false);
  assert.equal(pause.textContent, 'Pause prediction');
  assert.match(page.document.querySelector('#prediction-help').textContent, /Session expired/);
});

test('refresh reconnects to the saved job and cancellation removes its tab memory', async () => {
  const page = studio({ restore: true });
  await flush();
  const id = 'a'.repeat(32);
  assert.equal(page.document.querySelector('#v').src, '/video-jobs/' + id + '/source');
  assert.equal(page.document.querySelector('#prediction-pause').disabled, false);
  await page.document.querySelector('#prediction-cancel').onclick();
  page.advance();
  page.timers.at(-1)();
  await flush();
  assert.ok(page.deletedKeys.includes('medfire.currentVideoJob'));
});
