import { sourceDetections } from '/live-camera/coordinates.mjs';
const video = document.querySelector('#video'),
  overlay = document.querySelector('#overlay'),
  ctx = overlay.getContext('2d'),
  $ = (s) => document.querySelector(s);
let running = false,
  latest = [],
  sent = 0,
  drawFps = 0,
  drawTicks = [],
  lastDetect = 0,
  debug = new URLSearchParams(location.search).has('debug');
$('#debug').hidden = !debug;
let cameraSession = crypto.randomUUID(),
  generation = 0,
  lastResult = 0,
  starting = false;
async function cooldownRequest(method = 'GET', suffix = '', minutes) {
  const response = await fetch('/live-camera/cooldown' + suffix, {
    method,
    ...(minutes === undefined
      ? {}
      : {
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ minutes }),
        }),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.detail || 'Cooldown request failed');
  return data;
}
function cooldownBusy(busy) {
  for (const id of ['#cooldown-minutes', '#cooldown-save', '#cooldown-reset']) $(id).disabled = busy;
}
async function loadCooldown() {
  try {
    const data = await cooldownRequest();
    $('#cooldown-minutes').value = data.minutes;
    $('#cooldown-feedback').textContent =
      `Saved interval: ${data.minutes} min. Set 0 to disable the wait. Reset allows the next qualifying alert.`;
    cooldownBusy(false);
  } catch {
    $('#cooldown-feedback').textContent = 'Cooldown settings unavailable. Reload the page to retry.';
  }
}
$('#cooldown-save').onclick = async () => {
  const input = $('#cooldown-minutes');
  if (!input.reportValidity() || input.value === '') return;
  cooldownBusy(true);
  try {
    const data = await cooldownRequest('PUT', '', Number(input.value));
    $('#cooldown-feedback').textContent = `Saved: ${data.minutes} min. Applies immediately and after restart.`;
  } catch (error) {
    $('#cooldown-feedback').textContent = 'Could not save cooldown: ' + error.message;
  } finally {
    cooldownBusy(false);
  }
};
$('#cooldown-reset').onclick = async () => {
  cooldownBusy(true);
  try {
    await cooldownRequest('POST', '/reset');
    $('#cooldown-feedback').textContent = 'Wait reset. The next qualifying detection can send an alert.';
    if ($('#notice').textContent === 'Camera alert was suppressed by cooldown.') $('#notice').textContent = '';
  } catch (error) {
    $('#cooldown-feedback').textContent = 'Could not reset cooldown: ' + error.message;
  } finally {
    cooldownBusy(false);
  }
};
loadCooldown();
function fit() {
  const r = video.getBoundingClientRect(),
    d = devicePixelRatio || 1;
  overlay.width = Math.round(r.width * d);
  overlay.height = Math.round(r.height * d);
  ctx.setTransform(d, 0, 0, d, 0, 0);
}
function draw(expectedGeneration = generation) {
  if (!running || expectedGeneration !== generation) return;
  if (performance.now() - lastResult > 1500) latest = [];
  fit();
  const r = video.getBoundingClientRect(),
    vw = video.videoWidth,
    vh = video.videoHeight,
    scale = Math.min(r.width / vw, r.height / vh),
    ox = (r.width - vw * scale) / 2,
    oy = (r.height - vh * scale) / 2;
  ctx.clearRect(0, 0, r.width, r.height);
  ctx.lineWidth = 2;
  ctx.font = '13px system-ui';
  for (const d of latest) {
    const [x1, y1, x2, y2] = d.xyxy;
    ctx.strokeStyle = d.class === 'fire' ? '#ff684d' : '#ffc261';
    ctx.fillStyle = ctx.strokeStyle;
    ctx.strokeRect(ox + x1 * scale, oy + y1 * scale, (x2 - x1) * scale, (y2 - y1) * scale);
    ctx.fillText(d.class + ' ' + Math.round(d.confidence * 100) + '%', ox + x1 * scale + 3, oy + y1 * scale + 15);
  }
  const now = performance.now();
  drawTicks.push(now);
  while (drawTicks[0] < now - 1000) drawTicks.shift();
  drawFps = drawTicks.length;
  if (debug)
    $('#debug').textContent = JSON.stringify(
      { track: video.srcObject?.getVideoTracks()[0]?.getSettings(), drawFps, boxes: latest.length },
      null,
      2,
    );
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(() => draw(expectedGeneration));
  else requestAnimationFrame(() => draw(expectedGeneration));
}
async function detect(expectedGeneration = generation) {
  if (!running || expectedGeneration !== generation) return;
  if (video.readyState < 2) {
    setTimeout(() => detect(expectedGeneration), 120);
    return;
  }
  const now = performance.now();
  if (now - lastDetect < 140) {
    setTimeout(() => detect(expectedGeneration), 20);
    return;
  }
  lastDetect = now;
  const requestedGeneration = expectedGeneration;
  // Retain the exact source frame. Both detector copy and alert photo come from it.
  const full = document.createElement('canvas');
  full.width = video.videoWidth;
  full.height = video.videoHeight;
  full.getContext('2d').drawImage(video, 0, 0);
  const scale = Math.min(960 / full.width, 1),
    can = document.createElement('canvas');
  can.width = Math.max(1, Math.round(full.width * scale));
  can.height = Math.max(1, Math.round(full.height * scale));
  can.getContext('2d').drawImage(full, 0, 0, can.width, can.height);
  const blob = await new Promise((ok) => can.toBlob(ok, 'image/jpeg', 0.88));
  if (!running || expectedGeneration !== generation) return;
  try {
    const started = performance.now(),
      form = new FormData();
    form.append('image', blob, 'detector.jpg');
    const r = await fetch('/live-camera/detect', {
      method: 'POST',
      headers: { 'X-Camera-Session': cameraSession },
      body: form,
      signal: AbortSignal.timeout(10000),
    });
    const data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Detector failed');
    if (!running || requestedGeneration !== generation) return;
    lastResult = performance.now();
    latest = sourceDetections(data, full.width, full.height);
    $('#detect').textContent =
      'Detection ' +
      data.updates_per_second +
      '/s · ' +
      Math.round(performance.now() - started) +
      ' ms · ' +
      latest.length +
      ' boxes';
    if (data.alert_id) await snapshot(data.alert_id, full, expectedGeneration);
  } catch (e) {
    if (!running || expectedGeneration !== generation) return;
    latest = [];
    $('#notice').textContent = 'Detection unavailable: ' + e.message;
  }
  setTimeout(() => detect(expectedGeneration), 0);
}
async function snapshot(alertId, full, expectedGeneration) {
  const blob = await new Promise((ok) => full.toBlob(ok, 'image/jpeg', 0.94));
  if (!running || expectedGeneration !== generation) return;
  const form = new FormData();
  form.append('image', blob, 'live-camera-full.jpg');
  const r = await fetch('/live-camera/alert/' + alertId, {
    method: 'POST',
    body: form,
    signal: AbortSignal.timeout(10000),
  });
  if (!running || expectedGeneration !== generation) return;
  if (r.ok) {
    sent++;
    $('#notice').textContent = 'Full-resolution alert photo queued for Telegram.';
  } else {
    $('#notice').textContent = 'Alert photo could not be queued.';
  }
}
async function status(expectedGeneration = generation) {
  if (!running || expectedGeneration !== generation) return;
  if (running)
    try {
      const data = await fetch('/live-camera/status', { signal: AbortSignal.timeout(10000) }).then((r) => r.json());
      if (!running || expectedGeneration !== generation) return;
      $('#alert').textContent = 'Alerts ' + data.delivered + ' delivered · ' + data.failed + ' failed';
      if (data.last_error) $('#notice').textContent = data.last_error;
    } catch {}
  setTimeout(() => status(expectedGeneration), 1000);
}
$('#start').onclick = async () => {
  if (running) {
    stopCamera();
    return;
  }
  if (starting) return;
  starting = true;
  const startGeneration = generation;
  $('#start').disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
      audio: false,
    });
    if (startGeneration !== generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    video.srcObject = stream;
    await video.play();
    running = true;
    generation++;
    cameraSession = crypto.randomUUID();
    stream.getVideoTracks()[0].onended = stopCamera;
    const set = stream.getVideoTracks()[0].getSettings();
    $('#track').textContent = 'Negotiated ' + set.width + '×' + set.height + ' @ ' + (set.frameRate || '?') + ' fps';
    $('#start').textContent = 'Stop camera';
    draw();
    detect();
    status();
  } catch (e) {
    stopCamera();
    $('#notice').textContent = 'Camera permission or start failed: ' + e.name;
  } finally {
    starting = false;
    $('#start').disabled = false;
  }
};
const cameraStage = document.querySelector('.stage'),
  cameraHud = document.querySelector('.status');
cameraStage.append(cameraHud);
const fullscreenButton = document.createElement('button');
fullscreenButton.textContent = 'Fullscreen';
fullscreenButton.className = 'fullscreen-button';
cameraStage.append(fullscreenButton);
async function toggleCameraFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await cameraStage.requestFullscreen();
  } catch (e) {
    $('#notice').textContent = 'Fullscreen unavailable: ' + e.name;
  }
}
fullscreenButton.onclick = toggleCameraFullscreen;
cameraStage.ondblclick = toggleCameraFullscreen;
document.addEventListener('fullscreenchange', () => {
  fullscreenButton.textContent = document.fullscreenElement ? 'Exit fullscreen' : 'Fullscreen';
  fit();
});

function stopCamera() {
  running = false;
  generation++;
  latest = [];
  video.srcObject?.getTracks().forEach((track) => track.stop());
  video.srcObject = null;
  ctx.clearRect(0, 0, overlay.width, overlay.height);
  $('#start').textContent = 'Start camera';
  $('#track').textContent = 'Camera stopped';
  $('#detect').textContent = 'Detection waiting';
}
window.addEventListener('pagehide', stopCamera);
