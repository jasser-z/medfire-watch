import * as gl from 'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs';

import { createMapStyle } from '/world-map/style.mjs';

import { visibleDetections, createMapEntrance, satelliteFeedStatus } from '/world-map/logic.mjs';

import { installFireWeather } from '/fire-weather/module.mjs';

const $ = (id) => document.getElementById(id),
  debug = new URLSearchParams(location.search).has('debug');

let map,
  items = [],
  countries = [],
  searchIndex = -1,
  searchItems = [],
  lastUpdated = '',
  renderTicks = [],
  observed = true,
  refreshTimer,
  refreshing = false,
  lastObserved = '',
  feedRefreshing = false,
  feedError = '';

let entrance;
let satelliteHours = 24;

$('satellite-hours').value = String(satelliteHours);

const layers = ['observations', 'observations-glow', 'observation-clusters', 'observation-cluster-label'];

function message(text) {
  $('error').textContent = text;
  $('error').hidden = !text;
}

function featureCollection() {
  const end = Date.now(),
    visible = visibleDetections(items, end, satelliteHours);
  $('observations').textContent = visible.length.toLocaleString() + ' heat detections · last ' + satelliteHours + ' h';
  $('satellite-empty').hidden = visible.length > 0;
  return {
    type: 'FeatureCollection',
    features: visible.map((d) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [d.longitude, d.latitude] },
      properties: { ...d, age_hours: Math.max(0, (end - Date.parse(d.observed_at)) / 3600000) },
    })),
  };
}

function updateObservations() {
  if (map?.isStyleLoaded()) map.getSource('hotspots').setData(featureCollection());
  saveHash();
}

function fly(center, zoom = 10) {
  map.flyTo({ center, zoom, pitch: zoom >= 14 ? 50 : 0, duration: 900 });
}

function saveHash() {
  if (!map) return;
  const c = map.getCenter();
  history.replaceState(
    null,
    '',
    '#' +
      new URLSearchParams({
        lng: c.lng.toFixed(4),
        lat: c.lat.toFixed(4),
        z: map.getZoom().toFixed(2),
        pitch: map.getPitch().toFixed(0),
      }),
  );
}

$('observed').onchange = () => {
  observed = $('observed').checked;
  for (const id of layers) map?.setLayoutProperty(id, 'visibility', observed ? 'visible' : 'none');
  saveHash();
};

$('satellite-hours').onchange = () => {
  satelliteHours = Number($('satellite-hours').value);
  updateObservations();
};

function recent() {
  try {
    return JSON.parse(localStorage.getItem('medfire-searches') || '[]');
  } catch {
    return [];
  }
}

function displayResults(results) {
  searchItems = results;
  searchIndex = -1;
  $('results').replaceChildren();
  for (const item of results) {
    const b = document.createElement('button');
    b.textContent = item.label;
    b.onclick = () => {
      fly(item.center, item.zoom);
      map.fire('inspect-place', { lngLat: { lng: item.center[0], lat: item.center[1] } });
      $('place').value = item.label;
      $('results').replaceChildren();
      try {
        localStorage.setItem(
          'medfire-searches',
          JSON.stringify([item, ...recent().filter((x) => x.label !== item.label)].slice(0, 6)),
        );
      } catch {}
    };
    $('results').append(b);
  }
}

let timer,
  sequence = 0;
$('place').onfocus = () => {
  if (!$('place').value) displayResults(recent());
};
$('place').oninput = () => {
  clearTimeout(timer);
  const q = $('place').value.trim(),
    seq = ++sequence;
  if (q.length < 2) {
    displayResults(recent());
    return;
  }
  timer = setTimeout(async () => {
    let found = countries
      .filter((f) => f.properties.name.toLowerCase().includes(q.toLowerCase()))
      .slice(0, 3)
      .map((f) => ({ label: f.properties.name + ' · country', center: f.geometry.coordinates, zoom: 4 }));
    try {
      const r = await fetch(
        'https://geocoding-api.open-meteo.com/v1/search?name=' +
          encodeURIComponent(q) +
          '&count=6&language=en&format=json',
      );
      if (!r.ok) throw Error();
      const d = await r.json();
      found.push(
        ...(d.results || []).map((p) => ({
          label: [p.name, p.admin1, p.country].filter(Boolean).join(', '),
          center: [p.longitude, p.latitude],
          zoom: 12,
        })),
      );
    } catch {
      message('Place search temporarily unavailable.');
    }
    if (seq === sequence) displayResults(found);
  }, 350);
};

$('place').onkeydown = (e) => {
  const buttons = $('results').querySelectorAll('button');
  if (e.key === 'Escape') $('results').replaceChildren();
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    searchIndex = (searchIndex + (e.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    buttons.forEach((b, i) => b.classList.toggle('selected', i === searchIndex));
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    buttons[Math.max(0, searchIndex)]?.click();
  }
};

async function popup(e) {
  const f = e.features[0],
    d = f.properties,
    point = f.geometry.coordinates;
  const box = document.createElement('div');
  box.textContent =
    d.observed_at + ' · FRP ' + Number(d.frp).toFixed(1) + ' MW · ' + d.confidence + ' · ' + d.satellite;
  const town = document.createElement('p');
  box.append(town);
  new gl.Popup().setLngLat(point).setDOMContent(box).addTo(map);
  town.textContent = 'Looking up nearest catalogued town…';
  try {
    const r = await fetch('/world-map/nearest-town?latitude=' + point[1] + '&longitude=' + point[0]);
    const p = await r.json();
    town.textContent = p.available
      ? 'Nearest catalogued town: ' + p.name + ', ' + p.country + ' · ' + p.km.toFixed(1) + ' km · GeoNames'
      : 'Nearest-town catalogue unavailable.';
  } catch {
    town.textContent = 'Nearest-town lookup unavailable.';
  }
}

async function refresh() {
  if (refreshing) return;
  refreshing = true;
  clearTimeout(refreshTimer);
  try {
    const r = await fetch('/world-map/data', { cache: 'no-store', signal: AbortSignal.timeout(20000) });
    if (!r.ok) throw Error();
    const p = await r.json();
    items = visibleDetections(p.world.detections || [], Date.now());
    lastUpdated = p.world.updated_utc;
    feedRefreshing = p.refresh_in_progress === true;
    feedError = p.refresh_error || '';
    lastObserved = items.reduce((latest, d) => (d.observed_at > latest ? d.observed_at : latest), '');
    if (!map) {
      const hash = new URLSearchParams(location.hash.slice(1));
      observed = true;
      $('observed').checked = observed;
      map = new gl.Map({
        container: 'map',
        attributionControl: false,
        style: createMapStyle(featureCollection()),
        center: [Number(hash.get('lng') || 10), Number(hash.get('lat') || 15)],
        zoom: Number(hash.get('z') || 0),
        pitch: Number(hash.get('pitch') || 0),
        maxZoom: 19,
        maxPitch: 65,
      });

      map.addControl(new gl.AttributionControl({ compact: true }), 'bottom-right');

      const credits = map.getContainer().querySelector('.maplibregl-ctrl-attrib');

      let creditsOpened = false;

      function closeCredits() {
        if (!creditsOpened && credits) {
          credits.classList.remove('maplibregl-compact-show');
          credits.removeAttribute('open');
        }
      }

      credits?.querySelector('summary')?.addEventListener('click', () => {
        creditsOpened = credits.classList.contains('maplibregl-compact-show');
      });

      closeCredits();
      map.on('load', closeCredits);
      map.on('styledata', closeCredits);
      map.on('sourcedata', closeCredits);
      map.on('resize', closeCredits);

      map.addControl(new gl.FullscreenControl({ container: document.body }));
      map.addControl(new gl.ScaleControl(), 'bottom-right');
      map.on('moveend', saveHash);
      map.on('load', () => {
        $('observed').onchange();
        updateObservations();
        entrance = createMapEntrance(map, {
          reducedMotion: () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
          visible: () => document.visibilityState === 'visible',
        });
        entrance.play();
        const container = map.getContainer();
        for (const event of ['pointerdown', 'wheel', 'keydown'])
          container.addEventListener(event, () => entrance.cancel(), { passive: true, capture: true });
        if ('IntersectionObserver' in window) {
          const observer = new IntersectionObserver((entries) => {
            const showing = entries[0].isIntersecting;
            if (!showing) entrance.cancel();
            else map.resize();
          });
          observer.observe(container);
          map.on('remove', () => observer.disconnect());
        }
      });
      map.on('click', 'observations', popup);
      map.on('click', 'observation-clusters', async (e) => {
        const f = e.features[0],
          z = await map.getSource('hotspots').getClusterExpansionZoom(f.properties.cluster_id);
        fly(f.geometry.coordinates, z);
      });
      map.on('render', () => {
        const now = performance.now();
        renderTicks.push(now);
        while (renderTicks[0] < now - 1000) renderTicks.shift();
        if (debug)
          $('debug').textContent = JSON.stringify(
            {
              renderEventsPerSecond: renderTicks.length,
              zoom: map.getZoom(),
              features: items.length,
              updated: lastUpdated,
            },
            null,
            2,
          );
      });
      map.on('error', () => message('Some map tiles could not load.'));

      fetch('/world-map/countries/labels')
        .then((r) => r.json())
        .then((d) => (countries = d.features))
        .catch(() => {});
    } else updateObservations();
    $('satellite-status').textContent = satelliteFeedStatus(0, feedRefreshing, feedError);
  } catch {
    feedError = 'Could not check the satellite feed; cached observations shown.';
    $('satellite-status').textContent = feedError;
  } finally {
    refreshing = false;
    refreshTimer = setTimeout(refresh, 60000);
  }
}

setInterval(() => {
  if (!lastUpdated) return;
  const minutes = Math.max(0, Math.floor((Date.now() - Date.parse(lastUpdated)) / 60000));
  $('updated').textContent =
    'Feed checked ' +
    minutes +
    ' min ago · Last observed ' +
    (lastObserved
      ? new Date(lastObserved).toLocaleString([], {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        })
      : 'unavailable');
  $('satellite-status').textContent = satelliteFeedStatus(minutes, feedRefreshing, feedError);
}, 1000);

setInterval(updateObservations, 60000);

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    updateObservations();
    void refresh();
  } else entrance?.cancel();
});

window.addEventListener('pageshow', () => void refresh());

$('debug').hidden = !debug;
refresh();

const weatherInstaller = setInterval(() => {
  if (map?.isStyleLoaded()) {
    clearInterval(weatherInstaller);
    installFireWeather(map, $('layer-menu'));
  }
}, 200);

const tiltInstaller = setInterval(() => {
  if (map) {
    clearInterval(tiltInstaller);
    map.on('zoomend', () => {
      if (entrance?.isActive()) return;
      const pitch = map.getZoom() >= 14 ? 50 : map.getZoom() >= 10 ? 25 : 0;
      if (Math.abs(map.getPitch() - pitch) > 5)
        map.easeTo({ pitch, duration: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 600 });
    });
  }
}, 200);
