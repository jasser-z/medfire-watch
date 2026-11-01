# Third-party notices

Terms checked against provider pages on 2026-11-01. Project code is AGPL-3.0-only;
that license does not relicense datasets, imagery, map data or external services.
Runtime downloads and screenshots may carry separate conditions.

## Ultralytics YOLO

The detector uses Ultralytics and a YOLOv8-derived checkpoint.
[Ultralytics terms](https://www.ultralytics.com/legal/agpl-3-0-software-license)
provide AGPL-3.0 licensing; enterprise licensing is a separate option.
Preserve copyright and license notices, provide corresponding source when distributing
covered works, and meet the network-source obligations for modified server versions.
See [LICENSE](LICENSE). AGPL permits commercial use subject to its obligations.

## D-Fire and original image sources

[D-Fire license](https://github.com/gaia-solutions-on-demand/DFireDataset/blob/master/LICENSE)
dedicates the collection to CC0 while disclaiming ownership of underlying images.
Its [README](https://github.com/gaia-solutions-on-demand/DFireDataset) says original-provider
terms apply. Credit the GAIA researchers and cite de Venâncio, Lisboa and Barbosa,
*An automatic fire detection system based on deep convolutional neural networks for
low-power, resource-constrained devices*, Neural Computing and Applications (2022).
For D-Fire surveillance videos, cite de Venâncio et al., *A hybrid method for fire detection
based on spatial and temporal patterns* (2023).

- [HPWREN terms](https://www.hpwren.ucsd.edu/cc.html): archived data, including FIgLib,
  is CC BY-NC 4.0, copyright The Regents of the University of California.
  Credit HPWREN and UC San Diego with a source link; FIgLib additionally asks for
  Dewangan et al. (2022), *FIgLib & SmokeyNet*, Remote Sensing 14(4), 1007.
  Real-time data requires a separate license. Commercial archived-data permission requires
  registration, attribution, a share-back article, no dataset redistribution, no endorsement
  and renewed discussion at the stated revenue/acquisition conditions. No such registration
  or permission is documented here. Publications must carry this statement:
  “HPWREN data are not intended to be used as a decision-making tool, or as a replacement for such tools.”
- [FESB database](https://wildfire.fesb.hr/): official site retrieval failed during this review.
  D-Fire requests credit to the Center for Wildfire Research, FESB, University of Split,
  Croatia, Wildfire Observers and Smoke Recognition project. Exact current reuse and
  commercial permissions remain unverified; do not infer them from D-Fire's CC0.
- [FireNet repository](https://github.com/arpit-jadon/FireNet-LightWeight-Network-for-Fire-Detection):
  the README requests citation of Jadon, Omama, Varshney, Ansari and Sharma,
  *FireNet: A Specialized Lightweight Fire & Smoke Detection Model for Real-Time IoT
  Applications* (2019), arXiv:1905.11922. No explicit dataset redistribution license is
  visible in its root or README. Commercial and redistribution permissions remain unresolved.

These unresolved original-image rights prevent a blanket commercial-clearance claim for
the training corpus or supplied weights. The source-code license does not settle those rights.

## Pyro-SDIS

The [Pyronear dataset card](https://huggingface.co/datasets/pyronear/pyro-sdis)
declares Apache-2.0 and credits Pyronear volunteers and SDIS partners.
Retain the license, copyright and applicable NOTICE content when redistributing covered
material, and identify modifications. Cite the Pyronear Team, *Pyro-SDIS Dataset*, version 2.0 (2026).
Downloads pin their revision in `scripts/download_detection_data.py`; training images are external to this checkout.

## NASA FIRMS and NASA media

[NASA's FIRMS archive guidance](https://nrt4.modaps.eosdis.nasa.gov/archive/FIRMS/README.pdf)
promotes open reuse, including by private industry, and requests citation plus the disclaimer
when supplying data to others. Distinguish NRT from standard science products in publications.
Credit NASA FIRMS, NASA LANCE and the VIIRS SNPP NRT product; include observation/access
dates and the product-specific citation from the
[FIRMS citation policy](https://www.earthdata.nasa.gov/data/tools/firms/citation).
The [official S-NPP product record][snpp] identifies NASA/GSFC/EOS/ESDIS/LANCE MODIS FIRMS,
*VIIRS (S-NPP) I Band 375 m Active Fire Product NRT (Vector data)*,
[DOI 10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002](https://doi.org/10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002).
Accessed 2026-11-01; the application filters and renders the observations.
The citation-policy page itself was unavailable; exact required wording remains unverified.
[NASA media guidance](https://www.nasa.gov/nasa-brand-center/images-and-media/)
distinguishes NASA material from credited third-party material and protects insignia,
endorsement and identifiable-person rights. Check each clip's credit before redistribution.

[snpp]: https://data.nasa.gov/dataset/viirs-s-npp-i-band-375-m-active-fire-product-nrt-vector-data-ddc3b

## Copernicus EMS / GWIS / ECMWF

[GWIS data license](https://gwis.jrc.ec.europa.eu/about-gwis/data-license)
licenses EU-owned content under CC BY 4.0 unless otherwise indicated.
Credit European Union, Copernicus Emergency Management Service and GWIS, link the license,
and identify processing changes. Third-party content may need separate permission.
[ECMWF data terms](https://apps.ecmwf.int/datasets/licences/general/)
add prominent source attribution, copyright, license and warranty-disclaimer requirements.
This service is based on data and products of the European Centre for Medium-Range
Weather Forecasts (ECMWF). Source: [ECMWF](https://www.ecmwf.int/).
© 2026 ECMWF. Data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
ECMWF disclaims liability for errors, missing availability and resulting loss or damage.
The application caches provider display classes and renders map tiles and place lookups.

## Open-Meteo

[Open-Meteo terms](https://open-meteo.com/en/terms) distinguish CC BY 4.0 data from access
to the free API, which is non-commercial and limited to fewer than 10,000 daily,
5,000 hourly and 600 per-minute calls. Commercial access requires an appropriate subscription.
Credit Open-Meteo with a link, link CC BY 4.0, and identify changes or derived displays.
This application caches forecasts and formats local weather summaries.

## EOX Sentinel-2 cloudless

[EOX license summary](https://cloudless.eox.at/documentation/license) provides free
non-commercial use under CC BY-NC-SA 4.0; commercial use requires a separate EOX license.
Preserve attribution and share-alike conditions for adapted imagery; the project AGPL
does not replace them. Credit EOxCloudless, EOX IT Services GmbH and modified Copernicus
Sentinel data (2025), with links to [EOX](https://eox.at/) and
[EOxCloudless](https://cloudless.eox.at/). The mosaic is rendered as map tiles.
EOX restricts standalone resale and sublicensing under its commercial terms.

## OpenFreeMap / OpenStreetMap / OpenMapTiles

[OpenFreeMap's guide](https://openfreemap.org/quick_start/) displays credits to OpenFreeMap,
OpenMapTiles and OpenStreetMap. Keep these visible in map captures.
[OpenStreetMap data](https://www.openstreetmap.org/copyright) is ODbL: credit OpenStreetMap
contributors, link the license, and comply with database share-alike when distributing
adapted databases. Produced maps still require attribution.
[OpenMapTiles attribution](https://openmaptiles.org/docs/terminology/attribution/) requires
credit to OpenMapTiles and OpenStreetMap contributors; its schema is CC BY 4.0 and its
code uses BSD terms. These data licenses remain separate from MapLibre and application code.

## GeoNames and Natural Earth

[GeoNames](https://www.geonames.org/about.html) permits commercial reuse under
CC BY 4.0. Credit GeoNames with source and license links; the local catalogues
filter and format source records. No share-alike condition is stated on that page.
[Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) dedicates its raster
and vector data to the public domain. Attribution is optional; this project credits
Natural Earth for country boundaries and labels.

## FFmpeg and MapLibre

[FFmpeg licensing](https://ffmpeg.org/legal.html) depends on build configuration:
LGPL-2.1-or-later by default, GPL when optional GPL parts are enabled, and restrictions
for nonfree builds. Inspect `ffmpeg -version` and `-buildconf` for the installed executable.
If distributing binaries, include the applicable licenses, notices and corresponding
source/build information. This repository calls an installed/imageio-ffmpeg executable;
it does not ship an FFmpeg binary.

[MapLibre GL JS license](https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt)
uses BSD-3-Clause with embedded third-party notices. Preserve its copyright, conditions
and disclaimers in source/binary redistributions; do not imply contributor endorsement.
The dashboard loads the library from a CDN, whose distribution includes its notices.
