import {Popup} from 'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs';

export function currentDate(now = new Date(), timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC') {
  const parts = new Intl.DateTimeFormat('en', {timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(now);
  const value = type => parts.find(part => part.type === type).value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}

export async function installFireWeather(map, root) {
  let timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const section = document.createElement('div'); section.className = 'layer-group'; root.prepend(section);
  const heading = document.createElement('strong'); heading.textContent = 'Fire-weather danger'; section.append(heading);
  const clock = document.createElement('small'); section.append(clock);
  const status = document.createElement('small'); status.textContent = 'Loading latest available weather…'; section.append(status);
  const label = document.createElement('label'), check = document.createElement('input');
  check.type = 'checkbox'; check.checked = true;
  label.append(check, document.createTextNode(' Weather danger areas')); section.append(label);
  const legend = document.createElement('div'); section.append(legend);
  const missing = document.createElement('small'); missing.textContent = 'Uncoloured = no data.'; section.append(missing);
  const source = document.createElement('small'); section.append(source);
  const meaning = document.createElement('small'); meaning.textContent = 'Weather estimates, not a fire confirmation.'; section.append(meaning);
  let day = currentDate(), available = false, removed = false, inFlight, refreshAgain = false, lastAttempt = Date.now();
  let requestNumber = 0, activePopup, selectedPosition, placeBox;
  const timeFormat = () => new Intl.DateTimeFormat(undefined, {
    timeZone: timezone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'
  });
  let clockFormat = timeFormat();

  function visibility() {
    if (map.getLayer('fire-weather')) map.setLayoutProperty('fire-weather', 'visibility', available && check.checked ? 'visible' : 'none');
  }
  function popupMessage(text) { if (placeBox) placeBox.textContent = text; }
  function unavailable(message) {
    available = false; visibility(); ++requestNumber;
    status.textContent = message; status.style.color = '#ff9888';
    popupMessage("Today's weather is unavailable. Missing data does not mean safe.");
  }
  function tiles() { return [`/fire-weather/tiles/${day}/{z}/{x}/{y}.png?v=${Math.floor(Date.now() / 900000)}`]; }
  function renderLegend(classes) {
    legend.replaceChildren();
    const colors = ['#9cffc0', '#cde24e', '#e6ac00', '#d97010', '#ad060e', '#3a0015'];
    classes.forEach((item, i) => {
      const entry = document.createElement('span'); entry.style.cssText = 'display:inline-block;margin:4px;font-size:11px';
      const swatch = document.createElement('span'); swatch.style.cssText = 'display:inline-block;width:10px;height:10px;margin-right:4px;background:' + colors[i];
      entry.append(swatch, document.createTextNode(item.name)); legend.append(entry);
    });
  }
  async function refresh() {
    if (removed) return;
    if (inFlight) { refreshAgain = true; return inFlight; }
    lastAttempt = Date.now();
    inFlight = (async () => {
      const requestedDay = currentDate();
      try {
        const response = await fetch('/fire-weather/metadata?' + new URLSearchParams({timezone}), {cache: 'no-store'});
        if (!response.ok) throw Error();
        const meta = await response.json();
        if (removed) return;
        if (currentDate() !== requestedDay) { refreshAgain = true; throw Error(); }
        if (meta.timezone !== timezone || meta.today !== requestedDay || !meta.dates?.includes(requestedDay)) throw Error();
        day = requestedDay;
        const existing = map.getSource('fire-weather');
        if (existing) existing.setTiles(tiles());
        else {
          map.addSource('fire-weather', {type: 'raster', tiles: tiles(), tileSize: 256, maxzoom: 9, attribution: meta.attribution});
          map.addLayer({id: 'fire-weather', type: 'raster', source: 'fire-weather', paint: {'raster-opacity': .45, 'raster-fade-duration': 300}}, 'country-borders');
        }
        available = true; visibility(); renderLegend(meta.classes);
        source.textContent = 'Weather checked ' + new Date(meta.checked_utc).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
        status.textContent = ''; status.style.color = '';
        if (selectedPosition) void loadPlace();
      } catch {
        if (!removed) unavailable('OUTDATED / unavailable: no verified weather forecast for today · ' + currentDate() + '. Retrying automatically.');
      }
    })();
    try { await inFlight; }
    finally { inFlight = null; if (refreshAgain && !removed) { refreshAgain = false; void refresh(); } }
  }
  async function loadPlace() {
    const number = ++requestNumber, requestedDay = day, box = placeBox, position = selectedPosition;
    if (!box || !position) return;
    if (!available || requestedDay !== currentDate()) { popupMessage("Today's weather is loading or unavailable. Missing data does not mean safe."); return; }
    box.textContent = 'Loading current place weather…';
    const line = (text, strong = false) => {
      const p = document.createElement(strong ? 'strong' : 'p');
      p.style.cssText = 'display:block;margin:5px 0;line-height:1.4'; p.textContent = text; box.append(p);
    };
    try {
      const response = await fetch('/fire-weather/place?' + new URLSearchParams({latitude: position.lat, longitude: position.lng, date: requestedDay, timezone}), {cache: 'no-store'});
      if (!response.ok) throw Error();
      const data = await response.json();
      if (removed || number !== requestNumber || requestedDay !== currentDate() || !available) return;
      box.replaceChildren();
      line(data.nearest_town.available ? 'Near ' + data.nearest_town.name + ', ' + data.nearest_town.country : 'Selected location', true);
      line(data.valid_date + ' · ' + (data.weather_danger || 'Unavailable') + ' fire-weather danger', true);
      const w = data.weather;
      if (w.available && w.current?.time) {
          const interval = Number(w.current.interval) / 60;
          const rainLabel = interval > 0 ? 'Precipitation (' + interval + ' min)' : 'Precipitation';
          for (const [key, name] of [['temperature_2m', 'Temperature'], ['relative_humidity_2m', 'Humidity'], ['wind_speed_10m', 'Wind'], ['precipitation', rainLabel]])
            line(name + ': ' + (w.current[key] ?? 'unavailable') + ' ' + (w.current_units[key] || ''));
          const [weatherDate, weatherTime] = w.current.time.split('T');
          line('Weather at ' + (weatherDate === data.valid_date ? weatherTime : weatherDate + ' ' + weatherTime) + ' · ' + w.timezone);
      } else line('Current weather unavailable.');
      line('Weather estimates; not confirmed fire. Satellites can miss fires.');
    } catch {
      if (!removed && number === requestNumber) popupMessage('Current place weather unavailable. Missing data does not mean safe.');
    }
  }
  function inspect(position) {
    activePopup?.remove(); ++requestNumber;
    selectedPosition = position; placeBox = document.createElement('div'); placeBox.style.cssText = 'max-width:320px;max-height:65vh;overflow:auto';
    activePopup = new Popup({maxWidth: '350px'}).setLngLat(position).setDOMContent(placeBox).addTo(map);
    activePopup.on('close', () => { selectedPosition = null; placeBox = null; ++requestNumber; });
    void loadPlace(); if (!available) void refresh();
  }
  function tick() {
    if (removed) return;
    const deviceTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    const timezoneChanged = deviceTimezone !== timezone;
    if (timezoneChanged) { timezone = deviceTimezone; clockFormat = timeFormat(); }
    const now = new Date(), today = currentDate(now);
    clock.textContent = 'Your local time · ' + today + ' · ' + clockFormat.format(now) + ' · ' + timezone;
    if (timezoneChanged || today !== day) {
      day = today; unavailable('Loading today’s weather · ' + today + '…'); void refresh();
    } else if (!available && Date.now() - lastAttempt >= 60000) void refresh();
  }
  function resume() { tick(); void refresh(); }
  function visible() { if (document.visibilityState === 'visible') resume(); }
  check.onchange = visibility;
  map.on('error', e => { if (e.sourceId === 'fire-weather') unavailable('Weather tiles unavailable. No safe/low category inferred.'); });
  map.on('contextmenu', e => {
    e.preventDefault?.();
    e.originalEvent?.preventDefault();
    inspect(e.lngLat);
  });
  map.on('inspect-place', e => inspect(e.lngLat));
  const clockTimer = setInterval(tick, 1000), refreshTimer = setInterval(refresh, 15 * 60000);
  document.addEventListener('visibilitychange', visible);
  window.addEventListener('pageshow', resume); window.addEventListener('focus', resume);
  map.on('remove', () => {
    removed = true; ++requestNumber;
    clearInterval(clockTimer); clearInterval(refreshTimer);
    document.removeEventListener('visibilitychange', visible);
    window.removeEventListener('pageshow', resume); window.removeEventListener('focus', resume);
    activePopup?.remove();
  });
  tick(); await refresh();
}
