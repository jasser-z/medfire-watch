# Engineering hardening report — 2 November 2026

## A. Executive summary

The application now reserves video capacity before upload/preparation, protects active jobs and
downloads during retention, authenticates sensitive API reads, and supports native browser clients
through expiring HttpOnly sessions. Camera state and queue accounting are bounded; Telegram sends
and resets coordinate through reservations and generations. Media/settings validation, worker cleanup,
dependency reproducibility, CI checks and deployment documentation were strengthened.

This was a local source review and implementation, with automated regression and real inference checks.
It is not a penetration test, target-device acceptance test, new model evaluation or production certification.
No commits, pushes, model-weight edits, retraining or live Telegram messages were performed.

The existing CUDA environment still needs security migration. A separate patched CPU environment passed
the suite and dependency audit. Streamlit still requires an authenticated gateway when exposed remotely;
the API's session login does not establish dashboard access control.

## Review scope and previous work

Reviewed the tracked tree, English/French READMEs, requirements and project configuration, environment
template and exclusions, API middleware/routes/services, camera/Telegram/video pipelines, inference,
map/weather/geospatial integrations, browser modules, existing tests, CI and deployment/research/audit
documentation. Recent commits `5c023f5`, `d5b34a7` and `ebea36c` explained the previous changes.
Large model/catalogue/image artifacts were retained, not regenerated.

Previous fixes preserved include constant-time token comparison, Host/Origin checks, safe XML parsing,
image byte/pixel limits, per-session persistence, bounded video queues, inference locking/caching,
atomic weather writes, low-confidence VIIRS filtering and separate provider/detector interpretations.
The earlier report overstated active-job retention safety and strict video admission: those required fixes.

Implementation proceeded through lifecycle/admission, authentication, camera/Telegram coordination,
validation/worker cleanup, dependency checks and documentation. The first 20 new regression cases were
observed failing against the original source before the corresponding fixes. A later review also reproduced request cancellation deleting an input while its preparation thread was still active; the added regression now passes. Later tests cover additional
failures, negative inputs and newly added session/cancellation behavior.

## B. Issues fixed

Tests below are in [the hardening suite](../tests/test_hardening.py), unless another file is specified.
Every listed regression passes in the final suite.

| Severity | Root cause and resulting fix | Modified implementation | Regression evidence |
| --- | --- | --- | --- |
| High | Retention unlinked by file mtime before consulting active state. Sweep now locks lifecycle decisions/deletion, protects all active phases, uses terminal completion time and expires fileless failures. | `medfire_watch/retention.py`, `api/routers/video.py`, `api/services.py` | `test_retention_never_deletes_active_job_with_old_input` covers queued/processing/exporting/uploading/preparing with a 25-hour-old source; terminal/fileless/idempotence tests |
| High | Capacity checks preceded preparation without reserving a slot. UUID reservations now register atomically before body saving and persist until cleanup. Retained-state admission is capped separately. | `api/routers/video.py`, `api/services.py` | `test_parallel_admission_reserves_exact_capacity`: 24 attempts, exactly two admitted; simultaneous HTTP uploads and failure cleanup tests |
| High | Optional authentication excluded sensitive GET/HEAD requests. A public-read allow-list now protects alert history/photos, camera operations, job/source/export content and documentation endpoints. | `api/main.py` | `test_sensitive_reads_require_authentication`: nine paths, GET/HEAD denial and authorized access |
| High | Native clients lacked header tokens. Password-form login now issues signed eight-hour HttpOnly/SameSite cookies; HTTPS adds Secure; token rotation revokes sessions. No secrets are embedded in scripts or URLs. | `api/auth.py`, `api/main.py` | Browser login/download/logout/CSRF, expiry/tampering/rotation, camera inference and Telegram controls |
| High | Dashboard subprocesses did not inherit credentials loaded only inside the API. Launcher and direct Streamlit startup now load `.env`, preserving process-variable precedence. Remote launch without a token is rejected. | `scripts/run_app.py`, `dashboard/app.py`, `medfire_watch/config.py` | Two added launcher tests in `tests/test_launcher.py` |
| Medium | A sweep could unlink a terminal video while Starlette streamed it. Download leases now protect its artifact group and release in response finalization, including disconnects. | `api/routers/video.py`, `api/services.py`, `medfire_watch/retention.py` | `test_download_lease_survives_sweep_and_releases_on_disconnect` |
| High | Telegram cooldown check/send/update was not atomic across callers, and reset could be overwritten by an in-flight response. Per-state/key send reservations prevent concurrent duplicates; reset generations invalidate old timer updates; state writes are atomic. | `alerts/manager.py` | `test_telegram_concurrent_send_and_reset_during_network_wait`; existing cooldown/history tests |
| Medium | Reset did not rearm persistent tracks. It now clears trackers/pending candidates and invalidates queued old snapshots. Already transmitted requests cannot be recalled. | `api/routers/detection.py`, `medfire_watch/browser_camera.py` | Camera reset/session test and existing cooldown API tests |
| High | Camera trackers had idle eviction but no hard bound; queue bytes were incremented after publication. Session and inference admission are bounded, and snapshot byte reservations occur under the lock before queueing. Expired pending photos are rejected directly. | `medfire_watch/browser_camera.py`, `api/routers/detection.py` | Session expiry/reconnection, expired snapshot, concurrent snapshot budget and existing queue-limit tests |
| Medium | Browser capture loops and old responses could survive restart; stale boxes remained during stalled requests. Start/Stop, generation checks, request deadlines, stale-result clearing and page-exit track cleanup now coordinate capture. | `dashboard/live_camera.mjs`, `dashboard/video_player.mjs` | Behavioral restart/late-response/page-exit test in `tests/camera_lifecycle.test.mjs`; existing JS suites |
| High | Preparation and upload failures/cancellation could orphan files or leave reservations. Cleanup waits for an in-flight preparation thread after request cancellation before releasing capacity, and preserves terminal state for retry when Windows refuses deletion. Upload-body deadlines return 408. | `api/routers/video.py` | Upload size/disconnect, preparation failure, simultaneous requests, worker cancellation, and request-cancellation-during-preparation tests |
| Medium | Analysis could wait indefinitely on a queue and silently accept a short inference batch. Queue waits now detect dead/stalled decoders, batches must match, cancellation propagates, and decode-time duration limits cover unreliable frame counts. | `medfire_watch/video_analysis.py`, `medfire_watch/video.py` | Decoder exception, wrong result count, cancellation and real seek/export regression suites |
| Medium | Inference/export failure could leave intermediate files or mask the processing exception. Encoder/capture setup and finalization now close resources and remove partial output while preserving the original error. | `medfire_watch/video.py`, `medfire_watch/video_hardware.py` | `test_inference_failure_closes_export_and_removes_partial_files` uses a real short video and verifies Windows unlink succeeds |
| High | Negative/nonfinite TTLs and invalid limits were accepted or silently defaulted. Named numeric validation now rejects invalid settings and startup validates operational environment bounds. | `medfire_watch/config.py`, `api/services.py`, `api/main.py`, retention/video routers | Invalid TTL/job-limit and nine invalid detector-configuration cases |
| Medium | Decoder acceptance alone could admit unsupported container types; dimensions were checked after scaling in one path. Container signatures and finite metadata are checked before frame decoding, source dimensions are bounded, and FFmpeg subprocess protocols are restricted. | `api/routers/video.py`, `medfire_watch/video_hardware.py` | Empty/fake/playlist container rejection; existing real upload/export checks |
| Medium | Truncated image load errors escaped as server errors; still images ignored EXIF; malformed model boxes could propagate. Client errors, orientation normalization, finite/class checks and coordinate clipping now apply. | `api/routers/detection.py`, `api/services.py` | Truncated image, EXIF orientation and invalid/inverted/unknown/nonfinite model-output tests |
| High | HTTP-error exception chains could include the Telegram credential URL. Safe unchained errors now classify transient/non-retryable failures; missing credentials do not retry. | `alerts/manager.py`, `medfire_watch/browser_camera.py` | HTTP-error traceback redaction and five HTTP retry-policy cases; existing timeout/retry mocks |
| Medium | Satellite cache keys omitted file identity; raw provider coordinates could be out of range. Keys now include resolved path and nanosecond mtime; invalid provider coordinates are filtered. Request-created refresh threads were removed. | `medfire_watch/world_hotspots.py`, `api/routers/map.py` | Same-mtime/different-path test; existing satellite parsing and background refresh tests |
| Medium | Weather waiters recursively retried after failed shared metadata fetches. Failed/timed-out shared refresh now returns a bounded failure for a later caller to retry. | `medfire_watch/fire_weather.py` | Existing mocked weather success/failure and timezone suites; no outage load test |
| Medium | Alert-history reads materialized whole log files. Streaming bounded deques now retain only the requested recent entries and filter by channel. | `alerts/manager.py` | Existing alert/history/clear tests; no claimed throughput improvement |
| High, environment migration pending | Installed torch 2.5.1 has OSV findings. Runtime now pins a separately tested torch 2.14.1 / torchvision 0.29.2 pair, and constrained installs/advisory checks are available. The old CUDA installation was retained. | `requirements.txt`, `pyproject.toml`, `constraints-py311.txt`, `scripts/audit_dependencies.py`, CI | Full patched CPU suite, real inference, `pip check`, and OSV audit; CUDA migration remains outstanding |

## C. Architecture improvements

Kept FastAPI, Streamlit, shared model inference, local files and background threads. No new service,
database, queue infrastructure or identity framework was introduced. Reservations, transitions,
retention and leases use the existing job lock; terminal state has an explicit completion timestamp.
Workers retain capacity while cancellation is pending. Progress now accounts for analysis and export
separately instead of displaying completion before export finishes.

Authentication is a small token-to-cookie exchange. Streamlit remains a privileged backend client.
The existing model lock and bounded decode/encode queues remain; new checks address confirmed
lifecycle errors without rewriting the inference or map architecture.

## D. Security improvements and boundaries

See [deployment](DEPLOYMENT.md) for public routes, login, token rotation, CSRF/Origin handling,
same-site hostname requirements and ingress controls. Blank token mode is trusted loopback development.
Host validation is not a network access-control list. Remote deployments require an authenticated HTTPS
gateway covering both services, no direct service-port exposure, login/request rate limits, body limits
and disk quotas. Shared operator access provides no user/resource ownership isolation.

Use one API worker. Job/session/send coordination is process-local, and jobs are not resumed after
restart. Orphan groups age by newest mtime. Native codecs/drivers can block outside cooperative Python
cancellation; hostile media needs process/container limits. Container signatures are a prefilter, not a
complete parser or media sandbox.

The final scan checked 172 tracked/new source and artifact files against known local credential values, Telegram-token
patterns and private-key markers, with zero matches. It did not rescan all historical blobs or prove
the absence of every possible secret. No credential values were printed. The checkpoint, research
metrics, datasets/catalogues and screenshot assets were not modified.

The local CUDA torch version is affected by published checkpoint-loading advisories, including
[PyTorch's official advisory](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p).
The new audit normalizes CUDA version suffixes instead of skipping those distributions. Advisory records
can be aliases for the same CVE; record counts below are not unique vulnerability counts.

## E. Verification results

Baseline: **85 Python tests passed**, **21 JavaScript tests passed**; lint, formatting and local docs checks passed.
Final suite adds **64 Python cases** (62 hardening cases and two launcher cases) and **one JavaScript case**.

| Check | Final result |
| --- | --- |
| Python 3.11.9, original CUDA environment | 149 passed, 0 failed, 0 skipped; one upstream Starlette/httpx deprecation warning |
| Python 3.11.9, separate patched CPU environment | 149 passed, 0 failed, 0 skipped; same upstream warning |
| Python API/alerts/core line coverage | **85.08%** in both environments (2,121 of 2,493 statements); coverage is not hardware/browser acceptance |
| Node 22.22.0 tests and coverage command | 22 passed, 0 failed, 0 skipped |
| Measured JS line coverage | 96.81% in `camera_coordinates.mjs` and `map_logic.mjs` only; VM-evaluated controllers are not included in that percentage |
| Clean `npm ci` and npm advisory audit | Passed; zero reported npm vulnerabilities |
| Ruff / Prettier / seven browser-module syntax checks | Passed |
| Python compilation | Passed for API, alerts, core, dashboard, scripts and tests |
| Installed dependency consistency | `pip check` passed in both environments; the original CUDA pair does not satisfy the new source requirements |
| OSV, patched environment | 81 distributions checked; 0 packages with advisory records |
| OSV, original CUDA environment | Failed as expected: 88 distributions checked; torch 2.5.1 has 22 advisory records, including aliases |
| Launcher fast-development prerequisite check | Passed; no services started |
| Documentation and final diff whitespace checks | Passed: 109 local links and 25 readable images across 23 Markdown files; external URL reachability not certified |
| Hosted GitHub Actions | Not run; workflow edited locally |
| Live camera permissions, physical disconnects and full browser/gateway login acceptance | Not run on target hardware; controller behavior and HTTP contracts tested with mocks/TestClient |
| Live Telegram and provider outage/rate-limit acceptance | Not run; Telegram network behavior mocked; no live messages |
| New CUDA wheel/driver acceptance and sustained-load profiling | Not run |

An intermediate full run found seven downstream failures caused by a new launcher-test environment leak.
The fixture was corrected, the affected 31-test subset passed, and the full suites were rerun. Existing
assertions were not weakened. Old injected pending-snapshot/model-result fixtures were updated with
the expiry/original-shape metadata now required by the implementation. Test credentials are isolated
and restored; tests never write a real Telegram chat ID into `.env`.

Reproduce using a separate Python 3.11 environment:

```sh
python -m pip install --upgrade pip -c constraints-py311.txt
python -m pip install -r requirements-dev.txt -c constraints-py311.txt
python -m pip check
python -m ruff check .
python -m pytest -q --cov=api --cov=alerts --cov=medfire_watch --cov-report=term-missing
python -m compileall -q api alerts medfire_watch dashboard scripts tests
npm ci
npm test
npm run format:check
node scripts/check_ui_syntax.mjs
python scripts/check_docs.py
python scripts/audit_dependencies.py
npm audit
git diff --check
```

The CPU environment was initially staged with shared packages, then system-site access was disabled
and all missing constrained dependencies were installed before final checks. Final tests/audit used
that isolated package environment, retained at `%TEMP%\medfire-watch-audit-py311` for local review. Constraints provide exact tested versions, not artifact hashes or
a universal Linux/CUDA lock. Training extras remain separately version-ranged.

## F. Performance evidence

No new FPS, latency, memory-profile, precision, recall or mAP result is claimed. Existing research metrics
and benchmark artifacts were retained. Real inference succeeded with the patched CPU pair on a blank
360×640 BGR image, returning CPU/fp32 and zero detections. Real synthetic video tests checked frame
preservation/export and failure cleanup. Admission tests measured exactly two accepted reservations
from 24 concurrent attempts with a configured limit of two; this is correctness evidence, not a load benchmark.

History reads now bound resident entry collections, but still scan log files. Photos/logs require
operator retention/storage management. Provider/cache saturation and long-duration GPU stability were not profiled.

## G. Documentation improvements

Preserved the existing README layout and evaluation claims. Synchronized English/French installation
constraints, browser login/reset semantics, resource variables and Node 22 requirements. Expanded
`.env.example`, corrected weather-versus-video retention, and documented authentication boundaries,
single-worker coordination, cancellation, restart cleanup, ingress quotas and dependency migration.
Updated architecture, guide, demo, limitations, model-card runtime notes, changelog and the earlier audit's status.

Thermal anomalies, weather danger, visual fire/smoke detections and confirmed wildfire incidents remain
distinct. No new scientific contribution, false-alarm rate or real-world alert reliability is implied.

## H. Remaining risks and incomplete success criteria

1. **The original CUDA environment is still vulnerable and outside the new pinned requirements.**
   Passing functional tests there is not a security clearance. Only the separate patched CPU environment
   received a clean package-advisory result in this work.
2. **Remote deployment is conditional.** Streamlit needs its own authenticated gateway. API cookies do
   not provide user accounts or resource ownership. Public map/weather routes need ingress rate limiting.
3. **Resource isolation is incomplete for hostile media.** Python cancellation cannot guarantee
   interruption of every native decoder/driver operation. Multipart parsing occurs before route validation.
   Retained job counts bound registry accumulation, not total disk bytes. Alert photos/history are preserved
   and require an operator quota/archive policy.
4. **No durable/multi-worker coordination.** Use one API worker; restart does not resume jobs. Telegram
   timeouts can produce an accepted-but-unconfirmed message, so retry delivery is not exactly-once.
5. **Acceptance/research gaps remain.** Physical cameras, target browser HTTPS/iframe configuration,
   a patched GPU stack, sustained workload, live provider outages and live Telegram were not newly verified.
   Held-out false alarms per camera-hour and time-to-alert remain unmeasured. VFR export remains limited.
6. **Reproducibility has platform bounds.** Constraints are a tested Windows/Python 3.11 snapshot without
   hashes; hosted Linux CI and CUDA wheel compatibility require their own run. External documentation URL
   availability and historical secret scans were not newly certified.

These limits prevent an unconditional production-readiness claim or a claim that every success criterion
has been achieved on the current workstation.

## I. Prioritized next steps

1. Stage matching patched CUDA wheels and driver, rerun this suite/advisory scan, then verify real inference,
   decode, export and camera/Telegram acceptance before replacing the old environment.
2. Configure the authenticated HTTPS gateway, same-site hostnames, rate/body/connection limits and disk quotas;
   validate the full browser login/capture/upload/download flow there.
3. Run hosted Linux CI, sustained-media/resource tests and provider-failure exercises. For a hostile-input
   deployment, move decoding into a killable process boundary.
4. Use held-out annotated videos with capture timestamps to measure false alerts/camera-hour and time-to-alert
   at the documented thresholds. Record dataset IDs/hashes, hardware, confidence/IoU settings and evaluation
   commands; report confidence intervals without tuning on the held-out sample.

## J. Final Git diff and compatibility

All changes remain local and uncommitted. No tracked files were deleted. Source, tests and documentation
changed; weights, scientific results and required geospatial/media artifacts were preserved.

Behavior changes: when a token is configured, sensitive GET/HEAD/docs requests now need authentication;
native camera/video pages offer login. Invalid settings now fail instead of silently falling back. Upload
and retained-job saturation return 429; body deadline returns 408; unsupported/corrupt containers return
client errors. Video progress spans analysis and export. A cancellation endpoint is additive. Remote
launcher binding now requires a token. The runtime requires the new pinned model-library pair; the
existing CUDA environment is deliberately not upgraded in place.



Final inventory: **38 modified, 6 added, 0 deleted** files.

| Status | File |
| --- | --- |
| Modified | `.env.example` |
| Modified | `.github/workflows/ci.yml` |
| Modified | `CHANGELOG.md` |
| Modified | `README.fr.md` |
| Modified | `README.md` |
| Modified | `alerts/manager.py` |
| Modified | `api/main.py` |
| Modified | `api/routers/detection.py` |
| Modified | `api/routers/map.py` |
| Modified | `api/routers/video.py` |
| Modified | `api/services.py` |
| Modified | `dashboard/app.py` |
| Modified | `dashboard/live_camera.mjs` |
| Modified | `dashboard/video_player.mjs` |
| Modified | `docs/ARCHITECTURE.md` |
| Modified | `docs/AUDIT.md` |
| Modified | `docs/DEMO.md` |
| Modified | `docs/DEPLOYMENT.md` |
| Modified | `docs/GUIDE.md` |
| Modified | `docs/LIMITATIONS.md` |
| Modified | `docs/MODEL_CARD.md` |
| Modified | `medfire_watch/browser_camera.py` |
| Modified | `medfire_watch/config.py` |
| Modified | `medfire_watch/fire_weather.py` |
| Modified | `medfire_watch/retention.py` |
| Modified | `medfire_watch/video.py` |
| Modified | `medfire_watch/video_analysis.py` |
| Modified | `medfire_watch/video_hardware.py` |
| Modified | `medfire_watch/world_hotspots.py` |
| Modified | `pyproject.toml` |
| Modified | `requirements.txt` |
| Modified | `scripts/check_ui_syntax.mjs` |
| Modified | `scripts/run_app.py` |
| Modified | `tests/conftest.py` |
| Modified | `tests/test_browser_camera.py` |
| Modified | `tests/test_launcher.py` |
| Modified | `tests/test_phase3_correctness.py` |
| Modified | `tests/test_phase4_coverage.py` |
| Added | `api/auth.py` |
| Added | `constraints-py311.txt` |
| Added | `docs/HARDENING_REPORT.md` |
| Added | `scripts/audit_dependencies.py` |
| Added | `tests/camera_lifecycle.test.mjs` |
| Added | `tests/test_hardening.py` |
