# Earlier project audit — 2 November 2026

The current implementation and verification are in the [engineering hardening report](HARDENING_REPORT.md).
The findings and counts below describe the earlier snapshot; browser authentication, sensitive reads,
video admission and retention have since been corrected. The legacy CUDA environment still requires migration.

This earlier audit covers the current repository, setup documentation, Git exclusions, API guards,
camera cooldown controls, test suite, dependency advisories and reachable local Git history.
It is a source and automated-check review, not a penetration test or a new model evaluation.

## Corrections made

- Updated both READMEs with Telegram toolbar actions, camera cooldown controls and explicit
  Python 3.11 commands. Corrected setup-guide button names and the implemented-authentication roadmap text.
- Protected all mutation methods with the optional API token, including the new cooldown PUT route;
  token comparison uses a constant-time comparison.
- Added a unique camera-session header to browser detection requests so separate pages use separate trackers.
- Isolated two alert-manager tests from real local cooldown overrides.
- Fixed the UI syntax checker to work under Node 22 without experimental VM flags.
- Extended documentation checks to contribution/changelog files and reference-link destinations.
- Added Git exclusions for browser-review output and private certificate bundles.

## Verification

| Check | Result |
| --- | --- |
| Python tests | 85 passed |
| Python line coverage | 82.83% across API, alerts and medfire_watch |
| JavaScript tests | 21 passed |
| JavaScript measured line coverage | 96.81% in camera_coordinates.mjs and map_logic.mjs only |
| Ruff and browser asset formatting | Passed |
| UI module syntax | Passed |
| Local documentation links and images | Passed; external URL availability is not checked by this script |
| Installed dependency consistency | pip check passed |
| Launcher prerequisites | Fast-development check passed |
| NASA integration | Current configured FIRMS request returned HTTP 200 and observation CSV headers |
| npm dependency advisories | No reported vulnerabilities in the audited lockfile |
| Python dependency advisories | No findings in 86 scanned packages; CUDA packages required separate review below |
| Current release-file credential scan | No local credential values, Telegram-token patterns or private keys found |
| Reachable Git history scan | 342 blobs checked; no matching local credentials, Telegram-token patterns or private keys |
| Ignored files already tracked | None |

Coverage percentages do not imply complete browser, model or GPU coverage. The Python suite emits
one upstream Starlette/httpx deprecation warning. Credentials were not printed, and no Telegram
photo was sent during this audit.

## Git and media review

`.env`, environment variants, Streamlit secrets, runtime camera settings/timers/photos, logs,
provider caches, training outputs, virtual environments and node_modules are ignored.
The environment template, deployed checkpoint, required geospatial catalogues, screenshots and
documentation remain versioned. The largest tracked file is the checkpoint, about 22.5 MB;
the place catalogue is about 15.3 MB. No tracked file exceeds 100 MiB.

The credential scan checks known local values and specific secret patterns; it cannot prove that
every possible secret is absent. It covers locally reachable history, not remote-only or deleted history.
Media credits preserve source/license attribution without local paths or personal editing history.
The supplied Telegram illustration still has unverified underlying-image attribution; see
[media credits](media/CREDITS.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).

## Remaining findings

1. **Installed GPU dependency needs remediation.** The local environment contains
   `torch 2.5.1+cu121` and `torchvision 0.20.1+cu121`. The scanner initially skipped their CUDA
   version strings; auditing the base versions reported 22 advisory records for torch, with
   duplicate identifiers among those records. This is not a clean dependency audit.
   PyTorch confirms checkpoint-loading risks affecting older releases in
   [GHSA-53q9-r3pm-6pq6](https://github.com/pytorch/pytorch/security/advisories/GHSA-53q9-r3pm-6pq6)
   and [GHSA-63cw-57p8-fm3p](https://github.com/pytorch/pytorch/security/advisories/GHSA-63cw-57p8-fm3p).
   Use a reviewed, compatible current torch/torchvision/CUDA set and re-run inference and export checks.
   A patch version for one advisory is not an all-clear for the other records. The installed GPU
   stack was not replaced during this audit. The application accepts media uploads, not arbitrary model uploads;
   only load trusted checkpoints.
2. **Optional authentication is not integrated into native browser clients.** Streamlit server-side
   requests attach the configured token; camera/video iframe requests do not. Enabling the token
   therefore blocks their mutations unless a trusted proxy supplies the header. Read
   [deployment](DEPLOYMENT.md) before exposing the application. GET endpoints are not token-protected.
3. **Video capacity checks are not atomic reservations.** Capacity is checked before upload/preparation
   and job registration. Simultaneous requests can pass the check together; the setting is not a strict
   admission-control guarantee. Use a bounded reservation mechanism before multi-user deployment.
4. **Reproducibility and external behavior remain bounded.** Python dependencies use version ranges,
   not a complete lockfile. A fresh install can differ from this environment. Camera hardware,
   live Telegram delivery, provider outages, GPU upgrade compatibility, full VFR export behavior and
   held-out false-alarm rates were not newly validated by this audit.

The repository passes the listed automated checks. The remaining findings prevent an unconditional
security or production-readiness claim.

## CI follow-up

The map-route test previously depended on a local satellite cache, so a fresh checkout could fail.
It now uses an isolated temporary observation fixture and rejects external provider requests.
The neighbouring satellite parsing test now generates recent UTC observations instead of using a fixed date.
The exact CI pytest command passed with 85 tests in an isolated release copy without `.env`, integration
credentials, provider caches or runtime outputs. This verification used local Windows/Python 3.11;
the hosted Linux workflow still needs its own rerun.
