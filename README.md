# MedFire Watch

<a name="english"></a>

**A worldwide satellite and weather map with camera, image and video fire/smoke detection.**

MedFire Watch brings environmental awareness and computer vision into one local application. Explore recent satellite heat observations, inspect current fire-weather danger, analyse camera footage, and review automatic Telegram photo alerts.

[Français — ouvrir la traduction](#francais) · [Documentation](docs/INDEX.md) · [Model card](docs/MODEL_CARD.md) · [Limitations](docs/LIMITATIONS.md)

> Satellite heat observations are not confirmed wildfire incidents. Weather danger describes conditions favourable to fire, not the probability that a specific place will ignite. The application supports investigation; it does not replace emergency services.

## Features

| Page | What it does |
| --- | --- |
| **Fire danger** | Interactive satellite globe, country/city search, weather-danger overlay and recent satellite heat observations. Right-click a location for local weather. |
| **Live camera** | Browser webcam capture with fire/smoke detection and automatic annotated Telegram snapshots after persistent detections. |
| **Alerts** | Camera snapshot delivery history, including failures; Telegram chat connection and local history deletion. |
| **Test** | Image analysis and video playback with detection overlays, seek prioritisation and a downloadable annotated video. |

The map starts with the last **24 hours** of observations. Controls offer **1, 3, 6, 12 or 24 hours**. The globe entrance animation runs on opening/reloading; switching application tabs preserves the current map view.

### What is automatic?

- **Satellite:** the page checks every minute. While the API is running, a background worker also checks every minute; actual NASA retrieval is throttled to ten minutes. Old points expire according to the selected observation window.
- **Weather:** checked on opening, every fifteen minutes, at local midnight and when the tab becomes visible. Weather caches last up to fifteen minutes.
- **Camera alerts:** a background sender queues photo delivery and retries failures. Current alert rules require at least 50% confidence, a box covering at least 1% of the frame, and one second of spatially overlapping detections.

A feed check is different from a satellite observation. Automatic checks cannot remove satellite-pass, processing or forecast-provider delays. The satellite basemap is a dated mosaic, not a live camera view.

## Technology

Python 3.11 · FastAPI · Streamlit · MapLibre GL JS · Ultralytics YOLOv8s · PyTorch · OpenCV · FFmpeg · Telegram Bot API

The deployed detector recognises two classes: **fire** and **smoke**. GPU inference, CUDA video decoding/scaling and NVENC export are used when available; CPU fallbacks are supported. Browser playback frame rate and analysis throughput are different measurements.

## Installation

### 1. Requirements

- Python **3.11** and pip. Windows PowerShell is the documented setup.
- Internet access for satellite/weather providers, map tiles and initial dependency installation.
- A webcam for Live camera, or an image/video for Test.
- Optional NVIDIA GPU with a compatible driver and CUDA-enabled PyTorch installation. The validated development environment used an RTX 4060 and PyTorch 2.5.1+cu121. Other hardware needs its own acceptance checks.

Download or clone this repository, then open PowerShell in its root directory:

```powershell
cd medfire-watch
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The repository does not include `.venv`. Each machine creates its own environment. For GPU installation, follow the [official PyTorch installer](https://pytorch.org/get-started/locally/) for a build compatible with your machine. Do not copy another computer's environment.

### 2. Configure credentials

Create a local configuration file without overwriting one you already have:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` locally:

```dotenv
FIRMS_MAP_KEY=your_own_nasa_firms_map_key
TELEGRAM_BOT_TOKEN=your_own_bot_token
TELEGRAM_CHAT_ID=
```

- **FIRMS_MAP_KEY:** obtain a free key from [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/map_key/). This is a FIRMS MAP_KEY, not the general api.nasa.gov key.
- **Telegram settings:** needed only for camera photo delivery. Follow these steps:
  1. Open the official [BotFather](https://t.me/BotFather) in Telegram, send `/newbot` and follow its name/username prompts.
  2. Put the token supplied by BotFather into `TELEGRAM_BOT_TOKEN` in your local `.env`.
  3. Open your new bot and press **Start** or send `/start` from the account that should receive alerts.
  4. Leave `TELEGRAM_CHAT_ID` empty initially. Launch MedFire, open **Alerts** and click **Connect Telegram chat**. The application looks up and saves the chat ID locally. Alternatively, enter a known chat ID directly.
  5. Allow camera access in **Live camera**. Qualifying persistent detections trigger photo delivery; review delivered and failed attempts in **Alerts**. Do not create an uncontrolled fire to test the application.
- Satellite/weather access and Telegram delivery depend on their respective services and connectivity. Never commit `.env` or paste credentials into logs/issues.

### 3. Start the application

```powershell
.\.venv\Scripts\python.exe scripts\08_run_all_local.py
```

Open **http://127.0.0.1:8501**. API health is available at **http://127.0.0.1:8000/health**; interactive API documentation is at **http://127.0.0.1:8000/docs**.

To restart or stop this workspace's services:

```powershell
.\.venv\Scripts\python.exe scripts\08_run_all_local.py --restart
.\.venv\Scripts\python.exe scripts\08_run_all_local.py --stop
```

The trained detector must exist at `models/detection/weights/best.pt`. Required geographic catalogues live in `data/geospatial/`; `.gitignore` explicitly keeps these assets. Training datasets are not needed for inference. Runtime caches are created as needed.

## Quick walkthrough

1. **Fire danger:** open Controls, toggle weather/satellite layers and choose an observation window. Search for a city; right-click a location for its weather. Click a satellite point to inspect its time and location. Numbered clusters group observations, not confirmed fires.
2. **Live camera:** allow browser camera permission. The system requests frames from your device; actual resolution/FPS depend on hardware and browser negotiation. Persistent qualifying fire/smoke detections can trigger a Telegram photo.
3. **Alerts:** review delivered and failed camera attempts. **Delete all** clears local history/photos; it does not delete messages already delivered to Telegram.
4. **Test:** upload a JPG/PNG or supported video. Video limits default to **1 GB / 10 minutes**, configured in `configs/detection.yaml`. Fullscreen uses the video and overlay together. Download the annotated export after completion.

The current camera integration uses a PC webcam. A drone camera feed is an intended future integration, not an implemented drone-control or validated live-drone feature.

## Data and datasets

### Operational map

| Source | Purpose |
| --- | --- |
| NASA FIRMS VIIRS SNPP NRT | Recent satellite thermal observations |
| Copernicus EMS / GWIS / ECMWF | Official daily fire-weather danger classes |
| Open-Meteo | Local model-based weather and place search |
| EOX Sentinel-2 cloudless 2025 | Satellite background mosaic |
| OpenFreeMap / OpenStreetMap contributors | Detailed cartography, labels and buildings |
| GeoNames / Natural Earth | Place catalogue and geographic boundaries |

The map does not run a locally trained ignition model. Weather classes are provided by the external service; local weather does not constitute a causal explanation of that index. Uncoloured areas can mean missing data.

### Detector training data

The trained detector used **D-Fire** and **Pyro-SDIS**. D-Fire provides fire/smoke annotations and includes imagery from sources such as HPWREN, FESB and FireNet. Pyro-SDIS provides smoke and negative camera images; its smoke-only evaluation has no defined fire-class score.

- [D-Fire dataset and paper reference](https://github.com/gaia-solutions-on-demand/DFireDataset)
- [Pyro-SDIS dataset and licence](https://huggingface.co/datasets/pyronear/pyro-sdis)

Raw datasets, personal test media, intermediate checkpoints and processed outputs are intentionally excluded from the repository. Retained evaluation JSON, precision–recall curves and confusion matrices are in [docs/results](docs/results). Dataset redistribution and third-party use must follow each source's terms.

### Recorded detector results

These are retained evaluation results, not a new evaluation or a guarantee of deployment accuracy:

| Split | Precision | Recall | mAP50 | mAP50–95 |
| --- | ---: | ---: | ---: | ---: |
| D-Fire official held-out test | 0.740 | 0.681 | 0.747 | 0.419 |
| D-Fire validation | 0.749 | 0.669 | 0.747 | 0.434 |
| Pyro-SDIS validation, smoke only | 0.766 | 0.671 | 0.733 | 0.398 |

The D-Fire test report contains **4,306 images**. Detector confidence was selected using validation data; the current drawing threshold is about **0.298**. Camera alerting uses the stricter rules described above. See the [full metrics](docs/results/detection_final_metrics.json), [model card](docs/MODEL_CARD.md) and [performance notes](docs/VIDEO_BENCHMARK.md).

### Optional retraining

Retraining is separate from running the app and requires downloading datasets again:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-training.txt
```

The retained pipeline contains `01_download_detection_data.py` (pinned Pyro-SDIS export), `10_merge_detection_data.py` (merge and split protection), `02_verify_detection_data.py`, `03_train_detection.py` and `11_evaluate_detection.py`. D-Fire images/labels and official split lists must be obtained from the dataset provider before merging. Review the scripts' arguments and [data documentation](docs/DATA.md); the repository is not a bundled training dataset. Preserve the held-out test split and do not use it for tuning.

## Project layout

```text
api/                FastAPI routes and detection service
alerts/             Telegram delivery, cooldowns and history
configs/            Detector, alert and optional training settings
dashboard/          Streamlit UI, map and native camera/video components
medfire_watch/      Shared weather, satellite, detection and video logic
models/detection/   Deployed detector weights
scripts/            Launcher, data setup, refresh and optional training
tests/              Python and JavaScript regression tests
docs/               Architecture, model/data notes, guides and evaluation
data/geospatial/    Required geographic catalogues
```

`.venv/`, `runs/`, `logs/` and provider caches are local operational storage, excluded from Git. Do not publish camera snapshots or credentials. `.gitignore` keeps the deployed detector and required map catalogues while excluding training data and generated outputs.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check api alerts dashboard medfire_watch models scripts tests
Get-ChildItem tests -Filter '*.test.mjs' | ForEach-Object { node --test $_.FullName }
```

JavaScript checks require Node.js. They do not require uploading private media. Automated tests do not establish camera/browser compatibility or field detection accuracy on every machine.

## Troubleshooting

- **Python not found:** install Python 3.11 and confirm `py -3.11 --version` works.
- **Wrong directory:** run commands from the repository root, where `requirements.txt` is located.
- **Port already in use:** use the launcher's `--restart` for existing services from this workspace. Another application may require a different port; see `--help`.
- **No satellite updates:** check your FIRMS key, internet connection and source status. A fresh feed check can still contain older satellite observations.
- **No Telegram photo:** check bot/chat configuration, review failed attempts and verify that the camera alert persistence/confidence rules are met.
- **Slow video analysis:** verify whether PyTorch sees your GPU. CPU fallback can be slower than real time. Export quality and preview throughput are separate.

Logs stay in `logs/`. Optional Windows refresh tasks are documented in [Deployment](docs/DEPLOYMENT.md).

## Limits and credits

Satellites can miss fires; industrial heat can produce detections. Daily forecasts are not live weather sensors. Vision models can mistake clouds, reflections or haze for smoke/fire. Video export does not fully preserve variable-frame-rate timestamps. Physical browser/camera behaviour needs testing on the target machine. See [Limitations](docs/LIMITATIONS.md).

Credits: NASA FIRMS; European Union Copernicus EMS/GWIS and ECMWF; Open-Meteo; EOX; OpenFreeMap and OpenStreetMap contributors; GeoNames; Natural Earth; D-Fire authors and contributing sources HPWREN/FESB/FireNet; Pyronear and Pyro-SDIS contributors; Ultralytics, PyTorch and FFmpeg. Software, weights, datasets and provider services each retain their applicable licences and attribution requirements.


---

<a name="francais"></a>

<details>
<summary><strong>Français — cliquer pour afficher le guide en français</strong></summary>

**Carte mondiale satellite et météo, avec détection de feu et de fumée sur caméra, images et vidéos.**

[English](#english) · [Documentation](docs/INDEX.md) · [Modèle](docs/MODEL_CARD.md) · [Limites](docs/LIMITATIONS.md)

## Présentation

| Page | Fonction |
| --- | --- |
| Fire danger | Globe satellite, recherche de lieux, danger météorologique et observations thermiques récentes. Clic droit pour la météo locale. |
| Live camera | Détection par webcam et envoi automatique de captures annotées sur Telegram après une détection persistante. |
| Alerts | Historique des captures et des échecs de livraison, connexion du chat et suppression de l’historique local. |
| Test | Analyse d’images et lecture de vidéos avec rectangles de détection et export annoté téléchargeable. |

La caméra PC est l’intégration actuelle. La connexion d’un drone est une évolution prévue, pas une fonction validée.

**Les points satellites ne confirment pas un incendie.** Le danger météo indique des conditions favorables au feu, pas la probabilité d’un départ de feu précis. Le projet aide à examiner les signaux et ne remplace pas les secours.

## Installation sous Windows

Prérequis : Python **3.11**, accès Internet et, pour la caméra, une webcam. Le GPU NVIDIA est facultatif ; PyTorch doit être compatible avec le pilote pour utiliser CUDA. Le fonctionnement physique du navigateur et de la caméra doit être vérifié sur chaque machine.

Après téléchargement ou clonage du dépôt, ouvrir PowerShell à sa racine :

```powershell
cd medfire-watch
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Renseigner localement `.env` :

```dotenv
FIRMS_MAP_KEY=votre_cle_nasa_firms
TELEGRAM_BOT_TOKEN=votre_token
TELEGRAM_CHAT_ID=
```

La clé FIRMS s’obtient sur [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/api/map_key/). Telegram est nécessaire seulement pour les alertes photo :

1. Ouvrir le [BotFather officiel](https://t.me/BotFather), envoyer `/newbot` et suivre les instructions.
2. Renseigner le jeton reçu dans `TELEGRAM_BOT_TOKEN`, uniquement dans le fichier local `.env`.
3. Ouvrir le nouveau bot et lui envoyer `/start` depuis le compte destinataire des alertes.
4. Laisser `TELEGRAM_CHAT_ID` vide, lancer MedFire, puis ouvrir **Alerts → Connect Telegram chat**. L’application recherche et enregistre le chat localement. Un identifiant connu peut aussi être renseigné directement.
5. Autoriser la caméra dans **Live camera**, puis consulter les tentatives de livraison dans **Alerts**. Ne pas provoquer un feu réel pour tester.

Ne jamais publier `.env`.

```powershell
.\.venv\Scripts\python.exe scripts\08_run_all_local.py
```

Interface : **http://127.0.0.1:8501**. Documentation API : **http://127.0.0.1:8000/docs**.

Ajouter `--restart` pour relancer les services de ce projet, ou `--stop` pour les arrêter. Les journaux restent dans `logs/`.

Le dépôt conserve le détecteur `models/detection/weights/best.pt` et les catalogues géographiques nécessaires. `.venv`, les données d’entraînement, les caches, les vidéos traitées et les captures personnelles restent locaux et sont exclus de Git. Chaque machine crée son propre environnement.

## Utilisation et actualisation

- Dans Controls, choisir les observations des dernières **1, 3, 6, 12 ou 24 heures** ; 24 heures est le réglage initial. Les groupes numérotés sont des observations, pas des nombres d’incendies confirmés.
- La page et le service vérifient les satellites chaque minute ; le téléchargement NASA est limité à une fois toutes les dix minutes. Les passages et traitements satellites ajoutent un délai.
- La météo est vérifiée à l’ouverture, toutes les quinze minutes, à minuit local et au retour sur l’onglet. Les estimations météo ne sont pas des mesures de capteurs en direct.
- Les alertes caméra exigent actuellement au moins 50 % de confiance, une boîte occupant au moins 1 % de l’image et une seconde de détections spatialement cohérentes.
- Test accepte des images et des vidéos ; limites vidéo par défaut : **1 Go / 10 minutes**, configurables dans `configs/detection.yaml`.
- Delete all efface les captures et tentatives locales, sans supprimer les messages déjà reçus sur Telegram.

## Données et modèle

La carte utilise NASA FIRMS VIIRS SNPP, Copernicus EMS/GWIS/ECMWF et Open-Meteo. EOX Sentinel-2 cloudless 2025 fournit une mosaïque de fond datée ; OpenFreeMap/OpenStreetMap, GeoNames et Natural Earth fournissent la cartographie. La carte ne repose pas sur un modèle local entraîné de probabilité d’allumage.

Le détecteur YOLOv8s distingue **fire** et **smoke**. Les sources d’entraînement sont [D-Fire](https://github.com/gaia-solutions-on-demand/DFireDataset) et [Pyro-SDIS](https://huggingface.co/datasets/pyronear/pyro-sdis). D-Fire comprend notamment des images HPWREN, FESB et FireNet. Respecter les licences et attributions de chaque source.

| Évaluation conservée | Précision | Rappel | mAP50 | mAP50–95 |
| --- | ---: | ---: | ---: | ---: |
| Test officiel D-Fire, 4 306 images | 0,740 | 0,681 | 0,747 | 0,419 |
| Validation D-Fire | 0,749 | 0,669 | 0,747 | 0,434 |
| Validation Pyro-SDIS, fumée uniquement | 0,766 | 0,671 | 0,733 | 0,398 |

Ces résultats proviennent des rapports conservés ; aucune nouvelle évaluation n’est revendiquée. Voir [les métriques](docs/results/detection_final_metrics.json), [les données](docs/DATA.md) et [le modèle](docs/MODEL_CARD.md). Le seuil du détecteur a été choisi sur validation, sans ajustement sur le test final.

L’entraînement est facultatif. Installer `requirements-training.txt`, récupérer les données auprès de leurs auteurs, puis examiner les scripts de téléchargement, fusion, vérification, entraînement et évaluation. Les données brutes ne sont pas incluses ; voir le [guide anglais](#optional-retraining).

## Organisation et vérifications

`api/` : API ; `dashboard/` : interface ; `medfire_watch/` : logique partagée ; `alerts/` : Telegram ; `configs/` : réglages ; `models/` : poids ; `scripts/` : lancement et outils ; `tests/` : régressions ; `docs/` : documentation et résultats.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check api alerts dashboard medfire_watch models scripts tests
Get-ChildItem tests -Filter '*.test.mjs' | ForEach-Object { node --test $_.FullName }
```

Node.js est requis pour les tests JavaScript. Consulter [les limites](docs/LIMITATIONS.md) et [les performances mesurées](docs/VIDEO_BENCHMARK.md). Aucun résultat ne garantit une détection parfaite ou immédiate. La vidéo exportée ne préserve pas complètement les horodatages à fréquence variable.

[↑ English](#english)

</details>
