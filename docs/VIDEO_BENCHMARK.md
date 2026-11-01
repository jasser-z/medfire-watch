# Video performance

Historical measurements use an NVIDIA GeForce RTX 4060 development machine.
The available record does not specify CPU, RAM, operating system, driver versions or
repeated-run variance; results are hardware-specific samples.

| Measured case | Result |
| --- | --- |
| 1080p60 annotated export | 1,645 input frames; 1,645 output frames; 44.209 processing fps |
| GPU-scaled batch 8 analysis | 205.81 fps |
| Full-resolution batch 1 analysis | 21.56 fps in the same profiling comparison |
| Combined-validation PyTorch FP16 | mAP50 0.732433; precision 0.739594; recall 0.659397 |

Processing fps differs from playback fps. [Architecture](ARCHITECTURE.md) describes the runtime pipeline.

[Video metrics](results/video_detection/video_metrics.json) records two NASA-derived
12-second clips, each with 180 frames at 15 fps. The fire sample processes at
39.09772188815837 fps in 4.603848800063133 seconds; its 737,708-byte export has one event
at 0.26666666666666666 seconds following a first detection at 0 seconds.
The no-fire sample processes at 135.96723008135143 fps in 1.3238484000321478 seconds;
its 744,224-byte export has two events: detection/alert times 4.8/5.066666666666666
and 6.733333333333333/7.0 seconds. Both use confidence 0.2982982982982983 and a
five-consecutive-frame rule. Source URLs and all recorded values are in the JSON.
The source clips and exports are separate from the checkout.

Camera evaluation and reproducibility limits are in the [model card](MODEL_CARD.md)
and [limits](LIMITATIONS.md). Synthetic clips exercise frame preservation in the test suite.
