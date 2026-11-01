import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  satelliteFeedStatus,
  createMapEntrance,
  visibleDetections,
  playbackGate,
  contiguousFrontier,
} from '../dashboard/map_logic.mjs';
test('time window excludes future and stale detections', () => {
  const end = Date.parse('2026-10-28T00:00Z');
  assert.equal(
    visibleDetections(
      [
        { observed_at: '2026-10-27T00:00Z' },
        { observed_at: '2026-10-29T00:00Z' },
        { observed_at: '2026-10-24T00:00Z' },
      ],
      end,
    ).length,
    1,
  );
});
test('playback gate waits and resumes with hysteresis', () => {
  assert.equal(playbackGate(1, 1.05, false, false), 'wait');
  assert.equal(playbackGate(1, 2, false, true), 'wait');
  assert.equal(playbackGate(1, 2.5, false, true), 'play');
  assert.equal(playbackGate(10, 10, true, true), 'play');
});
test('seek gaps never count as an analysed buffer', () => {
  assert.ok(contiguousFrontier([{ time: 0 }, { time: 0.1 }, { time: 9 }], 0, 10) < 0.3);
  assert.equal(contiguousFrontier([{ time: 9 }, { time: 9.1 }], 9, 10), 9.2);
});

test('satellite windows use current time, inclusive boundaries and no stale fallback', () => {
  const end = Date.parse('2026-10-31T12:00Z');
  const data = [0, 1, 3, 6, 12, 24, 25].map((h) => ({ observed_at: new Date(end - h * 3600000).toISOString() }));
  assert.equal(visibleDetections(data, end).length, 6);
  for (const [h, n] of [
    [1, 2],
    [3, 3],
    [6, 4],
    [12, 5],
    [24, 6],
  ])
    assert.equal(visibleDetections(data, end, h).length, n);
  assert.deepEqual(visibleDetections(data.slice(2), end, 1), []);
  assert.equal(visibleDetections(data, end + 3600001, 1).length, 0);
});

test('entrance rotates through zoom in and out, returns to medium and releases manual navigation', () => {
  const moves = [],
    jobs = new Map();
  let clock = 0,
    serial = 0,
    stops = 0;
  const map = {
    stop() {
      stops++;
    },
    getCenter: () => ({ lng: 10, lat: 15 }),
    easeTo: (p) => moves.push(p),
    jumpTo: (p) => moves.push(p),
  };
  const options = {
    schedule: (fn) => {
      jobs.set(++serial, fn);
      return serial;
    },
    unschedule: (id) => jobs.delete(id),
    now: () => clock,
  };
  const next = () => {
    const [id, fn] = jobs.entries().next().value;
    jobs.delete(id);
    fn();
  };
  const entrance = createMapEntrance(map, options);
  entrance.cancel();
  assert.equal(stops, 0);
  entrance.play();
  entrance.play();
  assert.equal(moves.length, 1);
  assert.equal(moves[0].duration, 1300);
  assert.deepEqual(moves[0].center, [35, 15]);
  next();
  assert.equal(moves[1].zoom, 1.3);
  assert.equal(moves[1].duration, 1900);
  assert.deepEqual(moves[1].center, [65, 15]);
  next();
  assert.equal(entrance.isActive(), false);
  for (let i = 0; i < 10; i++) entrance.cancel();
  assert.equal(stops, 0, 'ordinary wheel/drag events must never call map.stop');
  clock = 4000;
  entrance.play();
  entrance.cancel();
  assert.equal(jobs.size, 0);
  assert.equal(stops, 1);
  entrance.cancel();
  assert.equal(stops, 1, 'subsequent scroll events must reach MapLibre undisturbed');
  clock = 8000;
  entrance.play();
  next();
  entrance.cancel();
  assert.equal(jobs.size, 0);
  assert.equal(stops, 2);
});
test('entrance respects reduced motion and hidden tabs', () => {
  const moves = [];
  const map = { stop() {}, easeTo: (p) => moves.push(p), jumpTo: (p) => moves.push(p) };
  createMapEntrance(map, { visible: () => false }).play();
  assert.equal(moves.length, 0);
  createMapEntrance(map, { reducedMotion: () => true }).play();
  assert.deepEqual(moves, [{ zoom: 1.3, pitch: 0, bearing: 0 }]);
});

test('satellite freshness status clears on recovery and distinguishes updating from failure', () => {
  assert.equal(satelliteFeedStatus(2, false, ''), '');
  assert.match(satelliteFeedStatus(16, true, ''), /Updating/);
  assert.match(satelliteFeedStatus(16, false, ''), /delayed/);
  assert.match(satelliteFeedStatus(0, false, 'Network unavailable.'), /Network unavailable/);
  assert.equal(satelliteFeedStatus(0, false, ''), '');
});

test('map entrance runs only on initial load, never when returning to a tab', () => {
  const source = readFileSync(new URL('../dashboard/earth_watch.mjs', import.meta.url), 'utf8');
  assert.equal((source.match(/entrance\.play\(\)/g) || []).length, 1);
  assert.equal((source.match(/entrance\?\.play\(\)/g) || []).length, 0);
  const visibility = source.slice(
    source.indexOf("document.addEventListener('visibilitychange'"),
    source.indexOf("$('debug').hidden"),
  );
  assert.doesNotMatch(visibility, /flyTo|easeTo|jumpTo|entrance.*play/);
  assert.match(source, /if\s*\(!showing\)\s*entrance.cancel\(\);\s*else\s*map.resize\(\)/);
});
