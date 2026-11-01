# Video performance evidence

These figures are earlier measurements on the development RTX4060 machine, not a guarantee on other hardware. Source test footage and disposable outputs are not required to run the app.

| Measured case | Result |
| --- | --- |
| 1080p60 annotated export | 1,645 input frames and 1,645 output frames; 44.209 processing fps |
| GPU-scaled batch8 analysis | 205.81 fps in the profiled case |
| Full-resolution batch1 analysis | 21.56 fps in the same profiling comparison |
| Combined-validation PyTorch FP16 | mAP50 0.732433; precision 0.739594; recall 0.659397 |

Processing speed and playback frame rate are different. The current UI uses native source-video playback, frame-aligned detection metadata, seek prioritisation and a separate annotated export. GPU decode/scale and NVENC are used when available; fallbacks run on CPU. Export preserves every decoded frame and copies compatible source audio.

Variable-frame-rate timestamps in exported files are not fully supported. Browser preview latency, physical fullscreen behaviour and negotiated camera frame rate need acceptance on the target machine. No new performance claim is made by the source cleanup. The removed preview/wait paths should not be assumed to have a measured speed gain.

For accuracy evidence see the retained detection metrics, PR curves and confusion matrices in docs/results. The active backend remains PyTorch. Install requirements-dev.txt for the automated checks. Tests build temporary synthetic clips; no personal test recording is required.
