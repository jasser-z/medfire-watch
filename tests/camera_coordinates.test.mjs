import { test } from 'node:test';
import assert from 'node:assert/strict';
import { sourceDetections } from '../dashboard/camera_coordinates.mjs';
test('960 detector image maps back to 1280 camera video', () => {
  const input = { image_width: 960, image_height: 540, detections: [{ class: 'fire', xyxy: [300, 150, 600, 450] }] };
  assert.deepEqual(sourceDetections(input, 1280, 720)[0].xyxy, [400, 200, 800, 600]);
  assert.deepEqual(input.detections[0].xyxy, [300, 150, 600, 450]);
});
test('odd aspect ratios use independent horizontal and vertical scales', () => {
  const input = { image_width: 960, image_height: 539, detections: [{ xyxy: [0, 0, 960, 539] }] };
  assert.deepEqual(sourceDetections(input, 1921, 1079)[0].xyxy, [0, 0, 1921, 1079]);
});
test('missing dimensions cannot silently draw misaligned boxes', () =>
  assert.throws(() => sourceDetections({ detections: [] }, 1280, 720)));
