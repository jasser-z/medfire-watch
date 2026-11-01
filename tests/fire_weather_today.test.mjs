import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../dashboard/fire_weather_layer.mjs', import.meta.url), 'utf8');
let moduleNumber = 0;

class Events {
  listeners = new Map();
  addEventListener(name, callback) {
    if (!this.listeners.has(name)) this.listeners.set(name, new Set());
    this.listeners.get(name).add(callback);
  }
  removeEventListener(name, callback) {
    this.listeners.get(name)?.delete(callback);
  }
  emit(name, event = {}) {
    for (const callback of this.listeners.get(name) || []) callback(event);
  }
  count() {
    return [...this.listeners.values()].reduce((total, callbacks) => total + callbacks.size, 0);
  }
}

class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.style = {};
    this.text = '';
  }
  set textContent(value) {
    this.text = value;
    this.children = [];
  }
  get textContent() {
    return this.text + this.children.map((child) => child.textContent ?? child).join('');
  }
  append(...children) {
    this.children.push(...children);
  }
  prepend(child) {
    this.children.unshift(child);
  }
  replaceChildren(...children) {
    this.text = '';
    this.children = children;
  }
  find(tag) {
    return [this, ...this.children.flatMap((child) => child.find?.(tag) || [])].filter((item) => item.tag === tag);
  }
}

class MapStub extends Events {
  sources = new Map();
  layers = new Map();
  popups = [];
  on(name, callback) {
    this.addEventListener(name, callback);
  }
  getSource(name) {
    return this.sources.get(name);
  }
  addSource(name, options) {
    this.sources.set(name, {
      ...options,
      setTiles(tiles) {
        this.tiles = tiles;
      },
    });
  }
  getLayer(name) {
    return this.layers.get(name);
  }
  addLayer(layer) {
    this.layers.set(layer.id, { ...layer, layout: {} });
  }
  setLayoutProperty(name, key, value) {
    this.layers.get(name).layout[key] = value;
  }
  queryRenderedFeatures() {
    return [];
  }
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const flush = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};

async function environment(run, { time = '2026-10-30T12:00:00Z', zone = 'Africa/Tunis' } = {}) {
  const original = Object.fromEntries(
    ['Date', 'fetch', 'document', 'window', 'setInterval', 'clearInterval', '__WeatherPopup'].map((key) => [
      key,
      Object.getOwnPropertyDescriptor(globalThis, key),
    ]),
  );
  const NativeDate = globalThis.Date,
    NativeFormat = Intl.DateTimeFormat;
  let now = NativeDate.parse(time),
    timerNumber = 0;
  const timers = new Map(),
    calls = [],
    root = new Element('root'),
    map = new MapStub();
  const document = new Events(),
    window = new Events();
  document.visibilityState = 'visible';
  document.createElement = (tag) => new Element(tag);
  document.createTextNode = (text) => ({ textContent: text });
  class FakeDate extends NativeDate {
    constructor(...args) {
      super(...(args.length ? args : [now]));
    }
    static now() {
      return now;
    }
  }
  globalThis.Date = FakeDate;
  Intl.DateTimeFormat = function (locale, options = {}) {
    return new NativeFormat(locale, { timeZone: zone, ...options });
  };
  globalThis.document = document;
  globalThis.window = window;
  globalThis.setInterval = (callback, delay) => {
    timers.set(++timerNumber, { callback, delay });
    return timerNumber;
  };
  globalThis.clearInterval = (id) => timers.delete(id);
  globalThis.__WeatherPopup = class extends Events {
    setLngLat(value) {
      this.position = value;
      return this;
    }
    setDOMContent(value) {
      this.box = value;
      return this;
    }
    addTo(value) {
      value.popups.push(this);
      return this;
    }
    on(name, callback) {
      this.addEventListener(name, callback);
      return this;
    }
    remove() {
      this.emit('close');
    }
  };
  let handler;
  globalThis.fetch = (url, options) => {
    calls.push({ url, options });
    return handler(url, options);
  };
  const module = await import(
    'data:text/javascript;base64,' +
      Buffer.from(
        source.replace(/^import\s*\{\s*Popup\s*\}[^\n]*\n/, 'const Popup = globalThis.__WeatherPopup;\n') +
          '\n//' +
          ++moduleNumber,
      ).toString('base64')
  );
  const metadata = (date = module.currentDate()) => ({
    today: date,
    dates: [date],
    checked_utc: new NativeDate(now).toISOString(),
    timezone: zone,
    attribution: 'Test provider',
    classes: [{ name: 'Low' }],
  });
  const response = (value) => ({ ok: true, json: async () => value });
  handler = async () => response(metadata());
  const env = {
    root,
    map,
    calls,
    document,
    window,
    timers,
    module,
    metadata,
    response,
    setTime(value) {
      now = NativeDate.parse(value);
    },
    setZone(value) {
      zone = value;
    },
    fetch(value) {
      handler = value;
    },
    tick(delay = 1000) {
      for (const timer of [...timers.values()]) if (timer.delay === delay) timer.callback();
    },
    visibility() {
      return map.getLayer('fire-weather')?.layout.visibility;
    },
  };
  try {
    await run(env);
  } finally {
    map.emit('remove');
    Intl.DateTimeFormat = NativeFormat;
    for (const [key, descriptor] of Object.entries(original)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor);
      else delete globalThis[key];
    }
  }
}

test('today follows local timezone and the UI has no date selector', { concurrency: false }, async () => {
  await environment(
    async (e) => {
      assert.equal(e.module.currentDate(new Date('2026-10-30T23:30Z'), 'Africa/Tunis'), '2026-10-31');
      assert.equal(e.module.currentDate(new Date('2026-10-31T00:30Z'), 'America/Los_Angeles'), '2026-10-30');
      await e.module.installFireWeather(e.map, e.root);
      assert.equal(e.root.find('select').length, 0);
      assert.match(e.root.textContent, /Your local time · 2026-10-31/);
      assert.equal(new URL(e.calls[0].url, 'http://test').searchParams.get('timezone'), 'Africa/Tunis');
      assert.match(e.map.getSource('fire-weather').tiles[0], /tiles\/2026-10-31\//);
    },
    { time: '2026-10-30T23:30Z' },
  );
});

test(
  'midnight hides yesterday immediately until the current-day request completes',
  { concurrency: false },
  async () => {
    await environment(
      async (e) => {
        await e.module.installFireWeather(e.map, e.root);
        const pending = deferred();
        e.fetch(() => pending.promise);
        e.setTime('2026-10-30T23:00:00Z');
        e.tick();
        assert.equal(e.visibility(), 'none');
        assert.match(e.root.textContent, /2026-10-31/);
        const check = e.root.find('input')[0];
        check.checked = true;
        check.onchange();
        assert.equal(e.visibility(), 'none', 'checkbox cannot reveal a stale forecast');
        pending.resolve(e.response(e.metadata()));
        await flush();
        assert.equal(e.visibility(), 'visible');
        assert.match(e.map.getSource('fire-weather').tiles[0], /tiles\/2026-10-31\//);
      },
      { time: '2026-10-30T22:59:59Z' },
    );
  },
);

test(
  'resuming a visible tab refreshes immediately without waiting fifteen minutes',
  { concurrency: false },
  async () => {
    await environment(async (e) => {
      await e.module.installFireWeather(e.map, e.root);
      assert.equal(e.calls.length, 1);
      e.document.visibilityState = 'hidden';
      e.document.emit('visibilitychange');
      assert.equal(e.calls.length, 1);
      e.document.visibilityState = 'visible';
      e.document.emit('visibilitychange');
      await flush();
      assert.equal(e.calls.length, 2);
      e.window.emit('pageshow');
      await flush();
      assert.equal(e.calls.length, 3);
    });
  },
);

test(
  'initial metadata failure retries automatically and stale metadata is never shown as today',
  { concurrency: false },
  async () => {
    await environment(async (e) => {
      e.fetch(async () => {
        throw Error('offline');
      });
      await e.module.installFireWeather(e.map, e.root);
      assert.equal(e.map.getLayer('fire-weather'), undefined);
      assert.match(e.root.textContent, /Retrying automatically/);
      e.fetch(async () => e.response(e.metadata('2026-10-29')));
      e.setTime('2026-10-30T12:01:00Z');
      e.tick();
      await flush();
      assert.equal(e.map.getLayer('fire-weather'), undefined, 'yesterday is rejected');
      e.fetch(async () => e.response(e.metadata()));
      e.setTime('2026-10-30T12:02:00Z');
      e.tick();
      await flush();
      assert.equal(e.visibility(), 'visible');
    });
  },
);

test('open place details follow midnight and reject an older in-flight response', { concurrency: false }, async () => {
  await environment(
    async (e) => {
      await e.module.installFireWeather(e.map, e.root);
      const oldPlace = deferred();
      const place = (date, danger) => ({
        valid_date: date,
        weather_danger: danger,
        nearest_town: { available: false },
        weather: { available: false },
        source: 'Test provider',
        checked_utc: '2026-10-30T23:00:00Z',
      });
      e.fetch(async (url) => {
        if (url.startsWith('/fire-weather/metadata')) return e.response(e.metadata());
        const params = new URL(url, 'http://test').searchParams;
        if (params.get('date') === '2026-10-30') return oldPlace.promise;
        return e.response(place('2026-10-31', 'Low'));
      });
      e.map.emit('inspect-place', { lngLat: { lat: 36.75, lng: 10.25 } });
      const box = e.map.popups[0].box;
      assert.match(box.textContent, /Loading current place weather/);
      e.setTime('2026-10-30T23:00:00Z');
      e.tick();
      assert.match(box.textContent, /unavailable/);
      await flush();
      assert.match(box.textContent, /2026-10-31 · Low/);
      oldPlace.resolve(e.response(place('2026-10-30', 'Extreme')));
      await flush();
      assert.match(box.textContent, /2026-10-31 · Low/);
      assert.doesNotMatch(box.textContent, /Extreme/);
    },
    { time: '2026-10-30T22:59:59Z' },
  );
});

test(
  'map teardown cancels refresh triggers and ignores an in-flight metadata result',
  { concurrency: false },
  async () => {
    await environment(async (e) => {
      const pending = deferred();
      e.fetch(() => pending.promise);
      const installed = e.module.installFireWeather(e.map, e.root);
      assert.equal(e.timers.size, 2);
      e.map.emit('remove');
      assert.equal(e.timers.size, 0);
      assert.equal(e.document.count(), 0);
      assert.equal(e.window.count(), 0);
      pending.resolve(e.response(e.metadata()));
      await installed;
      assert.equal(e.map.getLayer('fire-weather'), undefined);
      const before = e.calls.length;
      e.window.emit('focus');
      e.document.emit('visibilitychange');
      e.tick();
      assert.equal(e.calls.length, before);
    });
  },
);
test(
  'each visitor sees their own date, time and timezone independently of server location',
  { concurrency: false },
  async () => {
    for (const [zone, date, time] of [
      ['Europe/Paris', '2026-10-31', '00:30:00'],
      ['America/New_York', '2026-10-30', '19:30:00'],
      ['Asia/Tokyo', '2026-10-31', '08:30:00'],
    ]) {
      await environment(
        async (e) => {
          await e.module.installFireWeather(e.map, e.root);
          assert.ok(e.root.textContent.includes('Your local time · ' + date + ' · ' + time + ' · ' + zone));
          assert.equal(new URL(e.calls[0].url, 'http://test').searchParams.get('timezone'), zone);
          assert.ok(e.map.getSource('fire-weather').tiles[0].includes('/' + date + '/'));
        },
        { time: '2026-10-30T23:30Z', zone },
      );
    }
  },
);

test(
  'changing device timezone while open updates clock, forecast date and requests',
  { concurrency: false },
  async () => {
    await environment(
      async (e) => {
        await e.module.installFireWeather(e.map, e.root);
        e.setZone('America/New_York');
        e.tick();
        assert.equal(e.visibility(), 'none');
        await flush();
        assert.ok(e.root.textContent.includes('Your local time · 2026-10-30 · 19:30:00 · America/New_York'));
        assert.equal(new URL(e.calls.at(-1).url, 'http://test').searchParams.get('timezone'), 'America/New_York');
        assert.equal(e.visibility(), 'visible');
        assert.match(e.map.getSource('fire-weather').tiles[0], /tiles\/2026-10-30\//);
      },
      { time: '2026-10-30T23:30Z' },
    );
  },
);
