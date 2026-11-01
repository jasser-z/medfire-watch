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
function fit() {
  const r = video.getBoundingClientRect(),
    d = devicePixelRatio || 1;
  overlay.width = Math.round(r.width * d);
  overlay.height = Math.round(r.height * d);
  ctx.setTransform(d, 0, 0, d, 0, 0);
}
function draw() {
  if (!running) return;
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
  video.requestVideoFrameCallback?.(() => draw()) || requestAnimationFrame(draw);
}
async function detect() {
  if (!running || video.readyState < 2) {
    setTimeout(detect, 120);
    return;
  }
  const now = performance.now();
  if (now - lastDetect < 140) {
    setTimeout(detect, 20);
    return;
  }
  lastDetect = now;
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
  try {
    const started = performance.now(),
      form = new FormData();
    form.append('image', blob, 'detector.jpg');
    const r = await fetch('/live-camera/detect', { method: 'POST', body: form });
    const data = await r.json();
    if (!r.ok) throw Error(data.detail || 'Detector failed');
    latest = sourceDetections(data, full.width, full.height);
    $('#detect').textContent =
      'Detection ' +
      data.updates_per_second +
      '/s · ' +
      Math.round(performance.now() - started) +
      ' ms · ' +
      latest.length +
      ' boxes';
    if (data.alert_id) await snapshot(data.alert_id, full);
  } catch (e) {
    latest = [];
    $('#notice').textContent = 'Detection unavailable: ' + e.message;
  }
  setTimeout(detect, 0);
}
async function snapshot(alertId, full) {
  const blob = await new Promise((ok) => full.toBlob(ok, 'image/jpeg', 0.94));
  const form = new FormData();
  form.append('image', blob, 'live-camera-full.jpg');
  const r = await fetch('/live-camera/alert/' + alertId, { method: 'POST', body: form });
  if (r.ok) {
    sent++;
    $('#notice').textContent = 'Full-resolution alert photo queued for Telegram.';
  } else {
    $('#notice').textContent = 'Alert photo could not be queued.';
  }
}
async function status() {
  if (running)
    try {
      const data = await fetch('/live-camera/status').then((r) => r.json());
      $('#alert').textContent = 'Alerts ' + data.delivered + ' delivered · ' + data.failed + ' failed';
      if (data.last_error) $('#notice').textContent = data.last_error;
    } catch {}
  setTimeout(status, 1000);
}
$('#start').onclick = async () => {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
      audio: false,
    });
    video.srcObject = stream;
    await video.play();
    running = true;
    const set = stream.getVideoTracks()[0].getSettings();
    $('#track').textContent = 'Negotiated ' + set.width + '×' + set.height + ' @ ' + (set.frameRate || '?') + ' fps';
    $('#start').disabled = true;
    draw();
    detect();
    status();
  } catch (e) {
    $('#notice').textContent = 'Camera permission or start failed: ' + e.name;
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
