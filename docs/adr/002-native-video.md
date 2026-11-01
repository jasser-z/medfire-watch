# 2. Native playback and separate analysis

Status: Accepted

The browser renders original video with a canvas overlay. The API publishes frame-indexed
analysis and exports an annotated copy separately. GPU-scaled batches support throughput
while export preserves source resolution and decoded frame count.
