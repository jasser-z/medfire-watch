// Satellite imagery and real OpenStreetMap detail share Web Mercator tile coordinates.
// Satellite imagery stays visible at every zoom, with vector labels, roads and buildings above it.
export function createMapStyle(observations) {
  const name = ['coalesce', ['get', 'name:en'], ['get', 'name_en'], ['get', 'name']];
  const labelPaint = {'text-color': '#f1f7fc', 'text-halo-color': '#10212d', 'text-halo-width': 1.5};
  const places = [
    ['cities', 0, ['city'], 10, 19],
    ['towns', 6, ['town'], 11, 17],
    ['villages', 9, ['village', 'hamlet'], 11, 15],
    ['neighbourhoods', 12, ['suburb', 'quarter', 'neighbourhood'], 11, 14]
  ].map(([id, minzoom, classes, small, large]) => ({
    id, minzoom, type: 'symbol', source: 'detail', 'source-layer': 'place',
    filter: ['in', ['get', 'class'], ['literal', classes]],
    layout: {'text-field': name, 'text-font': ['Noto Sans Regular'], 'text-max-width': 8,
      'text-size': ['interpolate', ['linear'], ['zoom'], minzoom, small, 16, large],
      'text-padding': 5, 'symbol-sort-key': ['case', ['has', 'population'], ['-', 0, ['get', 'population']], ['coalesce', ['get', 'rank'], 10]]}, paint: labelPaint
  }));
  const style = {
    version: 8, projection: {type: 'globe'},
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    light: {anchor: 'viewport', color: '#ffecd6', intensity: 0.35},
    transition: {duration: 450, delay: 0},
    sources: {
      seamless: {type: 'raster',
        tiles: ['https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2025_3857/default/g/{z}/{y}/{x}.jpg'],
        tileSize: 256, maxzoom: 14,
        attribution: '<a href="https://maps.eox.at/">EOX::Maps</a> · <a href="https://cloudless.eox.at/">Sentinel-2 cloudless 2025</a> (modified Copernicus Sentinel data 2025)'},
      detail: {type: 'vector', url: 'https://tiles.openfreemap.org/planet',
        attribution: '<a href="https://openfreemap.org/">OpenFreeMap</a> · <a href="https://openmaptiles.org/">© OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a>'},
      countries: {type: 'geojson', data: '/world-map/countries/boundaries', attribution: 'Natural Earth'},
      labels: {type: 'geojson', data: '/world-map/countries/labels'},
      hotspots: {type: 'geojson', data: observations, cluster: true, clusterRadius: 42, clusterMaxZoom: 7}
    },
    layers: [
      {id: 'background', type: 'background', paint: {'background-color': '#e1dfd5'}},
      {id: 'seamless', type: 'raster', source: 'seamless', paint: {'raster-fade-duration': 400,
        'raster-opacity': 1}},
      {id: 'country-borders', type: 'line', source: 'countries', paint: {
        'line-color': '#d6e9f4', 'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.5, 7, 1.2], 'line-opacity': 0.4}},
      {id: 'road-casings', type: 'line', source: 'detail', 'source-layer': 'transportation', minzoom: 11,
        paint: {'line-color': '#586873', 'line-width': ['interpolate', ['exponential', 1.4], ['zoom'], 11, 1, 17, 9], 'line-opacity': 0.7}},
      {id: 'roads', type: 'line', source: 'detail', 'source-layer': 'transportation', minzoom: 9,
        filter: ['in', ['get', 'class'], ['literal', ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'minor', 'service']]],
        paint: {'line-color': ['match', ['get', 'class'], ['motorway', 'trunk'], '#ffd090', '#d2ebed'],
          'line-width': ['interpolate', ['exponential', 1.4], ['zoom'], 9, 0.4, 16, 3], 'line-opacity': 0.6}},
      {id: 'buildings-3d', type: 'fill-extrusion', source: 'detail', 'source-layer': 'building', minzoom: 14,
        filter: ['!', ['has', 'hide_3d']], paint: {
          'fill-extrusion-color': '#a1c7ce', 'fill-extrusion-opacity': 0.8,
          'fill-extrusion-height': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, ['coalesce', ['get', 'render_height'], 0]],
          'fill-extrusion-base': ['interpolate', ['linear'], ['zoom'], 14, 0, 14.6, ['coalesce', ['get', 'render_min_height'], 0]]}},
      {id: 'observations-glow', type: 'circle', source: 'hotspots', filter: ['!', ['has', 'point_count']], paint: {
        'circle-color': '#ff6c38', 'circle-radius': ['interpolate', ['linear'], ['zoom'], 0, 5, 6, 14],
        'circle-blur': 1, 'circle-opacity': 0.28}},
      {id: 'observation-clusters', type: 'circle', source: 'hotspots', filter: ['has', 'point_count'], paint: {
        'circle-color': ['interpolate', ['linear'], ['get', 'point_count'], 2, '#ffd46f', 30, '#ff641f', 200, '#ff2a3e'],
        'circle-radius': ['interpolate', ['linear'], ['get', 'point_count'], 2, 8, 200, 22], 'circle-opacity': 0.8,
        'circle-stroke-width': 0.8, 'circle-stroke-color': '#fff4bb'}},
      {id: 'observation-cluster-label', type: 'symbol', source: 'hotspots', filter: ['has', 'point_count'], layout: {'text-field': ['get', 'point_count_abbreviated'], 'text-font': ['Noto Sans Regular'], 'text-size': 11}, paint: {'text-color': '#13212b'}},
      {id: 'observations', type: 'circle', source: 'hotspots', filter: ['!', ['has', 'point_count']], paint: {
        'circle-color': ['interpolate', ['linear'], ['coalesce', ['get', 'age_hours'], 0], 0, '#ff382d', 12, '#ff983b', 48, '#d9cb9b'],
        'circle-radius': ['interpolate', ['linear'], ['coalesce', ['get', 'frp'], 0], 0, 3, 50, 7, 500, 13],
        'circle-opacity': ['interpolate', ['linear'], ['coalesce', ['get', 'age_hours'], 0], 0, 0.95, 48, 0.25],
        'circle-stroke-width': 0.7, 'circle-stroke-color': '#fff4bb'}},
      {id: 'country-names', type: 'symbol', source: 'labels', maxzoom: 8,
        layout: {'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 0, 10, 5, 17], 'text-max-width': 8}, paint: labelPaint},
      ...places,
      {id: 'street-names', type: 'symbol', source: 'detail', 'source-layer': 'transportation_name', minzoom: 14,
        layout: {'symbol-placement': 'line', 'text-field': name, 'text-font': ['Noto Sans Regular'],
          'text-size': 11, 'text-max-angle': 30, 'symbol-spacing': 300}, paint: labelPaint},
      {id: 'points-of-interest', type: 'symbol', source: 'detail', 'source-layer': 'poi', minzoom: 16,
        filter: ['<=', ['coalesce', ['get', 'rank'], 100], 3],
        layout: {'text-field': name, 'text-font': ['Noto Sans Regular'], 'text-size': 11,
          'text-max-width': 8, 'text-padding': 8}, paint: {...labelPaint, 'text-color': '#f7d8ac'}}
    ]
  };
  for(const layer of style.layers)if(['observations','observations-glow','observation-clusters','observation-cluster-label'].includes(layer.id))layer.layout={...(layer.layout||{}),visibility:'none'};
  return style;
}
