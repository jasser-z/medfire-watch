import { playbackGate, contiguousFrontier } from '/world-map/logic.mjs';
const v = document.getElementById('v'),
  c = document.getElementById('c'),
  stage = document.getElementById('stage'),
  ctx = c.getContext('2d');
const debugMode = new URLSearchParams(location.search).has('debug');
let clickedAt = 0,
  firstOverlayMs = null;
let maximumUploadBytes = 1024 ** 3;
if (debugMode) document.getElementById('hardware').textContent = 'Debug enabled · waiting for detector preparation.';
const play = document.getElementById('play'),
  seek = document.getElementById('seek');
let frames = [],
  done = false;
const savedJobKey = 'medfire.currentVideoJob';
let savedJob = null;
try {
  const value = JSON.parse(globalThis.sessionStorage?.getItem(savedJobKey) || 'null');
  if (value && /^[a-f0-9]{32}$/.test(value.id)) savedJob = value;
} catch {}
function rememberJob(id, fps) {
  try {
    if (id) globalThis.sessionStorage?.setItem(savedJobKey, JSON.stringify({ id, fps }));
    else globalThis.sessionStorage?.removeItem(savedJobKey);
  } catch {}
}
let jobId = 'JOB' === 'local' ? null : 'JOB',
  preparedInput = null,
  objectUrl = null,
  selectionSequence = 0,
  playSequence = 0,
  preparationAbort = null;
if (!jobId && savedJob) {
  jobId = savedJob.id;
  preparedInput = { input_id: jobId, initial_frames: [], source_fps: savedJob.fps || 30 };
}
let predictionPaused = false,
  predictionTerminal = false,
  cancellationRequested = false,
  controlBusy = false;
const pausePrediction = document.getElementById('prediction-pause'),
  cancelPrediction = document.getElementById('prediction-cancel');
function updatePredictionControls() {
  pausePrediction.disabled = !jobId || predictionTerminal || cancellationRequested || controlBusy;
  pausePrediction.textContent = predictionPaused ? 'Resume prediction' : 'Pause prediction';
  cancelPrediction.disabled =
    predictionTerminal || cancellationRequested || controlBusy || (!jobId && !preparationAbort);
}
async function predictionAction(action) {
  const requestedJob = jobId;
  if (!requestedJob || controlBusy) return;
  controlBusy = true;
  if (action !== 'resume') v.pause();
  if (action === 'cancel') cancellationRequested = true;
  updatePredictionControls();
  try {
    const response = await fetch('/video-jobs/' + requestedJob + '/' + action, {
      method: 'POST',
      signal: AbortSignal.timeout(10000),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || 'Could not update prediction');
    if (requestedJob !== jobId) return;
    if (action === 'cancel') {
      document.getElementById('prediction-help').textContent =
        'Cancelling… waiting for the current operation to finish.';
    } else {
      predictionPaused = result.paused;
      document.getElementById('prediction-help').textContent = predictionPaused
        ? 'Prediction paused. Progress is kept; press Resume prediction to continue.'
        : 'Prediction resumed.';
      if (!predictionPaused) v.play().catch(() => {});
    }
  } catch (error) {
    if (requestedJob === jobId) {
      cancellationRequested = false;
      document.getElementById('prediction-help').textContent = error.message;
    }
  } finally {
    controlBusy = false;
    updatePredictionControls();
  }
}
pausePrediction.onclick = () => predictionAction(predictionPaused ? 'resume' : 'pause');
cancelPrediction.onclick = () => {
  if (jobId) return predictionAction('cancel');
  preparationAbort?.abort();
  preparationAbort = null;
  selectionSequence++;
  predictionTerminal = true;
  frames = [];
  v.pause();
  document.getElementById('status').textContent = 'Upload cancelled. Choose a video to start again.';
  document.getElementById('check').textContent = 'Predict live ↗';
  updatePredictionControls();
};
if (jobId) {
  v.src = '/video-jobs/' + jobId + '/source';
  stage.dataset.playing = 'true';
} else {
  v.autoplay = false;
  fetch('/video-test/prepare', { method: 'POST' })
    .then((r) => {
      if (!r.ok) throw Error();
      return r.json();
    })
    .then((d) => {
      maximumUploadBytes = d.maximum_upload_bytes || 1024 ** 3;
      document.getElementById('limit-copy').textContent =
        'Original quality and native playback · MP4 / WebM / MOV · up to ' +
        (maximumUploadBytes / 1024 ** 2).toFixed(0) +
        ' MiB / ' +
        (d.maximum_duration_seconds / 60).toFixed(1) +
        ' minutes';
      if (!preparedInput)
        document.getElementById('hardware').textContent =
          d.video_encoder === 'h264_nvenc'
            ? 'NVIDIA NVENC ready · select a video'
            : 'Software encoder fallback · select a video';
    })
    .catch(() => (document.getElementById('hardware').textContent = 'Detector will be prepared with your video.'));
  const upload = document.getElementById('upload'),
    picker = document.getElementById('file');
  upload.style.display = 'flex';
  document.getElementById('status').textContent = 'Ready · choose a video to begin.';
  async function selectFile(file) {
    if (!file) return;
    if (jobId && !predictionTerminal) {
      fetch('/video-jobs/' + jobId + '/cancel', { method: 'POST' }).catch(() => {});
    }
    const sequence = ++selectionSequence;
    if (preparationAbort) preparationAbort.abort();
    preparationAbort = new AbortController();
    preparedInput = null;
    jobId = null;
    rememberJob(null);
    predictionPaused = predictionTerminal = cancellationRequested = false;
    updatePredictionControls();
    document.getElementById('prediction-help').textContent = 'Upload can be cancelled while preparing.';
    playSequence++;
    frames = [];
    done = false;
    gatePaused = false;
    gatePauses = 0;
    analysisFinished = false;
    const check = document.getElementById('check');
    check.disabled = true;
    document.getElementById('filename').textContent = file.name + ' · ' + (file.size / 1024 / 1024).toFixed(1) + ' MB';
    if (file.size > maximumUploadBytes) {
      preparationAbort = null;
      updatePredictionControls();
      document.getElementById('status').textContent = 'File exceeds the configured upload limit.';
      return;
    }
    v.pause();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(file);
    v.src = objectUrl;
    stage.dataset.playing = 'true';
    document.getElementById('download').replaceChildren();
    document.getElementById('download').style.display = 'none';
    document.getElementById('progress-fill').style.width = '0%';
    document.getElementById('progress').setAttribute('aria-valuenow', '0');
    check.textContent = 'Preparing…';
    document.getElementById('status').textContent = 'Uploading and preparing the first second for instant prediction…';
    const suffix = '.' + file.name.split('.').pop().toLowerCase();
    try {
      const response = await fetch('/video-upload?suffix=' + encodeURIComponent(suffix), {
        method: 'POST',
        body: file,
        signal: preparationAbort.signal,
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw Error(detail.detail || 'Video upload failed');
      }
      const input = await response.json();
      if (sequence !== selectionSequence) return;
      preparedInput = input;
      frames = [...input.initial_frames];
      jobId = input.input_id;
      rememberJob(jobId, input.source_fps);
      preparationAbort = null;
      updatePredictionControls();
      document.getElementById('prediction-help').textContent = 'Pause keeps progress for Resume. Cancel ends the job.';
      check.disabled = false;
      check.textContent = 'Predict live ↗';
      document.getElementById('status').textContent = 'Ready · press Predict live';
      document.getElementById('hardware').textContent =
        input.width +
        ' × ' +
        input.height +
        ' · ' +
        input.source_fps.toFixed(2) +
        ' fps · ' +
        (input.detector_device === '0'
          ? 'CUDA ' + input.detector_precision.toUpperCase()
          : 'Detector ' + input.detector_device) +
        ' · ' +
        (input.video_decoder === 'cuda-nvdec' ? 'NVDEC' : 'CPU decode fallback') +
        ' · ' +
        (input.video_encoder === 'h264_nvenc' ? 'NVENC' : 'CPU encode fallback');
    } catch (e) {
      if (sequence === selectionSequence) {
        preparationAbort = null;
        updatePredictionControls();
        check.textContent = 'Predict live ↗';
        document.getElementById('status').textContent =
          'Video preparation failed: ' + (e.message || 'Check the file and choose it again.');
      }
    }
  }
  picker.onchange = () => {
    const file = picker.files[0];
    picker.value = '';
    selectFile(file);
  };
  upload.ondragover = (e) => {
    e.preventDefault();
    upload.classList.add('dragging');
  };
  upload.ondragleave = () => upload.classList.remove('dragging');
  upload.ondrop = (e) => {
    e.preventDefault();
    upload.classList.remove('dragging');
    selectFile(e.dataTransfer.files[0]);
  };
  document.getElementById('check').onclick = async () => {
    if (!preparedInput || cancellationRequested || (predictionTerminal && !done)) return;
    if (predictionPaused) return predictionAction('resume');
    const input = preparedInput,
      sequence = selectionSequence;
    playSequence++;
    clickedAt = performance.now();
    firstOverlayMs = null;
    if (!frames.length) frames = [...input.initial_frames];
    jobId = input.input_id;
    v.currentTime = 0;
    stage.dataset.playing = 'true';
    v.play().catch(() => {});
    document.getElementById('download').replaceChildren();
    document.getElementById('download').style.display = 'none';
    document.getElementById('status').textContent = 'Predicting live…';
    document.getElementById('check').disabled = true;
    try {
      let response = await fetch('/video-inputs/' + input.input_id + '/predict', { method: 'POST' });
      if (!response.ok) throw Error();
      const job = await response.json();
      if (sequence === selectionSequence) jobId = job.video_id;
    } catch (e) {
      if (sequence === selectionSequence)
        document.getElementById('status').textContent = 'Could not start prediction. Choose the video again.';
    } finally {
      if (sequence === selectionSequence)
        document.getElementById('check').disabled = cancellationRequested || (predictionTerminal && !done);
    }
  };
}
play.onclick = () => {
  if (v.src) {
    if (v.paused) v.play().catch(() => {});
    else v.pause();
  }
};
v.onplay = () => (play.textContent = 'Pause');
v.onpause = () => (play.textContent = 'Play');
document.getElementById('audio').onclick = () => {
  v.muted = !v.muted;
  document.getElementById('audio').textContent = v.muted ? 'Unmute' : 'Mute';
};
seek.oninput = () => {
  if (v.duration) v.currentTime = (seek.value / 1000) * v.duration;
};
v.onseeking = () => {
  if (jobId && !analysisFinished)
    fetch('/video-jobs/' + jobId + '/seek?seconds=' + v.currentTime, { method: 'POST' }).catch(() => {});
};
v.ontimeupdate = () => {
  seek.value = v.duration ? (v.currentTime / v.duration) * 1000 : 0;
  document.getElementById('time').textContent =
    Math.floor(v.currentTime / 60) + ':' + String(Math.floor(v.currentTime % 60)).padStart(2, '0');
};
function fullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else
    stage.requestFullscreen().catch(() => {
      document.getElementById('status').textContent = 'Fullscreen permission was denied by the browser';
    });
}
document.getElementById('fullscreen').onclick = fullscreen;
stage.ondblclick = fullscreen;
v.onloadedmetadata = () => (stage.style.aspectRatio = v.videoWidth + '/' + v.videoHeight);
v.onerror = () =>
  (document.getElementById('status').textContent = 'This browser cannot play the source codec. Use an H.264 MP4.');
let lastStatus = 0;
let gatePaused = false,
  gatePauses = 0,
  analysisFinished = false;
setInterval(() => {
  if (!jobId || !frames.length || analysisFinished || predictionPaused || cancellationRequested || predictionTerminal)
    return;
  const frontier = contiguousFrontier(frames, v.currentTime, preparedInput?.source_fps || 30),
    ahead = frontier - v.currentTime;
  const decision = playbackGate(v.currentTime, frontier, analysisFinished, gatePaused);
  if (!v.paused && decision === 'wait') {
    v.pause();
    gatePaused = true;
    gatePauses++;
  } else if (gatePaused && decision === 'play') {
    gatePaused = false;
    v.play().catch(() => {});
  }
  if (gatePaused) document.getElementById('status').textContent = 'Analysing ahead… · pauses ' + gatePauses;
  if (debugMode)
    document.getElementById('hardware').textContent =
      'Analysed ahead ' +
      ahead.toFixed(2) +
      ' s · gate pauses ' +
      gatePauses +
      ' · first boxes ' +
      (firstOverlayMs === null ? 'waiting' : firstOverlayMs.toFixed(1) + ' ms');
}, 50);
async function poll() {
  if (!jobId) {
    setTimeout(poll, 50);
    return;
  }
  const requestedJob = jobId,
    requestedPlay = playSequence;
  try {
    let r = await fetch('/video-jobs/' + requestedJob + '/frames?since=' + frames.length);
    if (r.status === 404 && requestedJob === jobId) {
      jobId = preparedInput = null;
      rememberJob(null);
      frames = [];
      predictionTerminal = true;
      v.pause();
      document.getElementById('download').replaceChildren();
      document.getElementById('check').disabled = true;
      document.getElementById('status').textContent = 'Video results were cleared or expired. Choose a video again.';
      updatePredictionControls();
      setTimeout(poll, 500);
      return;
    }
    if (!r.ok) throw Error();
    let data = await r.json();
    if (requestedJob !== jobId || requestedPlay !== playSequence) {
      setTimeout(poll, 50);
      return;
    }
    frames.push(...data.frames);
    frames.sort((a, b) => a.time - b.time);
    if (Date.now() - lastStatus < 500) {
      setTimeout(poll, 50);
      return;
    }
    lastStatus = Date.now();
    let response = await fetch('/video-jobs/' + requestedJob);
    if (!response.ok) throw Error();
    let s = await response.json();
    if (requestedJob !== jobId || requestedPlay !== playSequence) {
      setTimeout(poll, 50);
      return;
    }
    predictionPaused = !!s.paused;
    predictionTerminal = ['complete', 'failed', 'cancelled'].includes(s.status);
    cancellationRequested = !!s.cancellation_requested && !predictionTerminal;
    if (predictionPaused || cancellationRequested) v.pause();
    updatePredictionControls();
    if (predictionTerminal) document.getElementById('check').disabled = s.status !== 'complete';
    analysisFinished = !!s.analysis_complete || predictionTerminal;
    if (
      analysisFinished &&
      gatePaused &&
      !predictionPaused &&
      !cancellationRequested &&
      s.status !== 'cancelled' &&
      s.status !== 'failed'
    ) {
      gatePaused = false;
      v.play().catch(() => {});
    }
    let percentage = Math.min(100, Math.max(0, Math.round((s.fraction || 0) * 100)));
    document.getElementById('progress-fill').style.width = percentage + '%';
    document.getElementById('progress').setAttribute('aria-valuenow', String(percentage));
    document.getElementById('status').textContent =
      s.status === 'cancelled'
        ? 'Prediction cancelled. Choose the video again to start a new prediction.'
        : cancellationRequested
          ? 'Cancelling prediction…'
          : predictionPaused
            ? 'Prediction paused · ' + s.frames_processed + ' frames analysed'
            : s.status === 'failed'
              ? 'Detection failed: ' + s.error
              : 'Playing · ' +
                s.frames_processed +
                ' frames analysed' +
                (s.status === 'complete' ? ' · analysis complete' : '');
    if (s.status === 'cancelled' || s.status === 'failed') {
      rememberJob(null);
      frames = [];
      v.pause();
      document.getElementById('prediction-help').textContent = 'Job ended. Choose a video to start again.';
    }
    if (s.status === 'complete' && !done) {
      done = true;
      let a = document.createElement('a');
      a.href = '/videos/' + jobId + '/download';
      a.textContent = '↓ Download annotated video';
      document.getElementById('download').append(a);
      document.getElementById('download').style.display = 'block';
    }
  } catch (e) {
    if (requestedJob === jobId) document.getElementById('status').textContent = 'Detector connection interrupted';
  }
  setTimeout(poll, done ? 500 : 50);
}
poll();
function draw(mediaTime = v.currentTime) {
  let w = stage.clientWidth,
    h = stage.clientHeight,
    dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  let vw = v.videoWidth || 1,
    vh = v.videoHeight || 1,
    scale = Math.min(w / vw, h / vh),
    ox = (w - vw * scale) / 2,
    oy = (h - vh * scale) / 2;
  let lo = 0,
    hi = frames.length - 1,
    best = -1;
  // Binary search the latest analysed frame at the displayed media timestamp.
  // A short age bound prevents boxes from lingering across an unanalysed gap.
  while (lo <= hi) {
    let m = (lo + hi) >> 1;
    if (frames[m].time <= mediaTime + 0.0001) {
      best = m;
      lo = m + 1;
    } else hi = m - 1;
  }
  if (best >= 0 && mediaTime - frames[best].time < 0.3)
    for (let d of frames[best].detections) {
      let [x, y, x2, y2] = d.xyxy;
      if (clickedAt && firstOverlayMs === null) firstOverlayMs = performance.now() - clickedAt;
      let color = d.class === 'fire' ? '#ff4238' : '#ffb02e';
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(ox + x * scale, oy + y * scale, (x2 - x) * scale, (y2 - y) * scale);
      ctx.font = '15px system-ui';
      let text = d.class + ' ' + Math.round(d.confidence * 100) + '%',
        tx = ox + x * scale,
        ty = Math.max(18, oy + y * scale - 8);
      ctx.fillStyle = color;
      ctx.fillRect(tx, ty - 17, ctx.measureText(text).width + 10, 21);
      ctx.fillStyle = '#000';
      ctx.fillText(text, tx + 5, ty);
    }
  if (v.requestVideoFrameCallback) v.requestVideoFrameCallback((now, metadata) => draw(metadata.mediaTime));
  else requestAnimationFrame(() => draw(v.currentTime));
}
draw();

window.addEventListener('pagehide', () => {
  preparationAbort?.abort();
  v.pause();
  if (objectUrl) URL.revokeObjectURL(objectUrl);
});
