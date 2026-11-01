export function sourceDetections(response, width, height) {
  if (!(response.image_width > 0 && response.image_height > 0 && width > 0 && height > 0))
    throw Error('Missing camera coordinate dimensions');
  return (response.detections || []).map((d) => ({
    ...d,
    xyxy: d.xyxy.map((v, i) =>
      Math.max(
        0,
        Math.min(v * (i % 2 ? height / response.image_height : width / response.image_width), i % 2 ? height : width),
      ),
    ),
  }));
}
