# Day 12-14 recording timing audit

Scope: 13 WT7/WT8 sessions recorded October 4-6, 2026, excluding calibration. An initially visible October 7 Learn directory contained no files and was absent on the final inventory. Older WT5/WT6 September sessions are outside this recent-session audit.

**Finding:** There is both genuine loss of recorded time points and delayed delivery of retained frames. Six sessions have substantial camera deficits. Missing images cannot be reconstructed, but the surviving frames can be mapped to the 1b timeline using camera timestamps. All originals remain unchanged.

## Frame counts

MP4 container frame counts, writer counts, CSV row counts, and NPY dimensions agree for all 52 camera recordings. This checks count consistency; it is not a full video decode or image-content integrity check.

| Session | 1b saved | 3b saved | 4b saved | 5b saved | GPIO entries |
|---|---:|---:|---:|---:|---:|
| WT7_day12_outdoorLearn_100426 | 190,861 | 187,611 | 190,865 | 190,468 | 190,861 |
| WT7_day12_outdoorMem_100426 | 163,312 | 163,308 | 163,312 | 163,312 | 163,312 |
| WT7_day13_outdoorLearn_100526 | 136,887 | 136,883 | 136,887 | 136,885 | 136,887 |
| WT7_day13_outdoorMem_100526 | 150,721 | 150,716 | 150,721 | 150,721 | 150,725 |
| WT7_day14_outdoorLearn_100626 | 227,103 | 227,094 | 227,103 | 227,096 | 154,383 |
| WT8_day12_outdoorLearn_100426 | 180,294 | 180,293 | 180,294 | 180,293 | 180,294 |
| WT8_day12_outdoorMem_100426 | 192,712 | 192,712 | 189,144 | 192,714 | 192,712 |
| WT8_day13_outdoorLearn_100526 | 217,081 | 216,577 | 217,083 | 215,662 | 217,081 |
| WT8_day13_outdoorMem_100526 | 92,940 | 92,939 | 92,940 | 92,940 | 92,940 |
| WT8_day13_outdoorMemS2_100526 | 32,298 | 32,296 | 30,892 | 32,297 | 32,298 |
| WT8_day14_outdoorLearn_100626 | 92,769 | 92,766 | 92,770 | 92,767 | 92,769 |
| WT8_day14_outdoorLearnS2_100626 | 221,916 | 219,719 | 219,964 | 210,272 | 221,916 |
| WT8_day14_outdoorMem_100626 | 72,685 | 72,684 | 71,583 | 72,685 | 72,685 |

## Missing time points relative to 1b

The next table counts frames present in 1b with no corresponding saved image in another camera. It includes missing tails and is not simply subtraction of total frame counts. The mapping assumes each camera's first saved frame belongs to the same trigger. Common triggering, initial host-arrival offsets of 0-22 ms, and matching end trigger indices in most cameras support that assumption, but absolute offsets need visual/common-event validation.

| Session | Missing in 3b | Missing in 4b | Missing in 5b | Largest excess delivery lag |
|---|---:|---:|---:|---:|
| WT7_day12_outdoorLearn_100426 | 3,256 | 2 | 399 | 14.43 s |
| WT7_day12_outdoorMem_100426 | 4 | 0 | 0 | 0.31 s |
| WT7_day13_outdoorLearn_100526 | 4 | 0 | 2 | 0.13 s |
| WT7_day13_outdoorMem_100526 | 5 | 0 | 0 | 0.33 s |
| WT7_day14_outdoorLearn_100626 | 9 | 0 | 7 | 11.45 s |
| WT8_day12_outdoorLearn_100426 | 1 | 0 | 1 | 0.16 s |
| WT8_day12_outdoorMem_100426 | 2 | 3,570 | 0 | 16.07 s |
| WT8_day13_outdoorLearn_100526 | 507 | 1 | 1,422 | 16.02 s |
| WT8_day13_outdoorMem_100526 | 1 | 0 | 0 | 0.31 s |
| WT8_day13_outdoorMemS2_100526 | 2 | 1,406 | 1 | 14.85 s |
| WT8_day14_outdoorLearn_100626 | 4 | 0 | 3 | 0.14 s |
| WT8_day14_outdoorLearnS2_100626 | 2,197 | 1,952 | 11,644 | 15.69 s |
| WT8_day14_outdoorMem_100626 | 1 | 1,102 | 0 | 14.64 s |

1b itself has 6 missing 25-ms slots in WT7 day12 Learn, 2 in WT8 day12 Mem, 3 in WT8 day13 Learn, and 1 in WT8 day14 Learn. GPIO has gaps at exactly the same ordinal positions in those sessions. Consequently, a camera can have more total frames than 1b while still missing different frames that 1b saved.

## What the stalls look like

The large losses are repeated short gaps concentrated in bad periods, not single multi-thousand-frame holes. The largest individual internal gap is six missing slots (150 ms of absent samples, 175 ms between surviving frames). The configured 5-second chunk length controls status reporting; it does not establish a 5-second video-loss mechanism.

Examples: WT7 day12 Learn 3b loses 3,256 internal slots across 3,090 gaps; WT8 day14 LearnS2 5b loses 11,200 internal slots across 10,150 gaps and ends 444 trigger slots (11.10 seconds) before 1b. WT8 day12 Mem 4b has 3,485 internal missing slots plus an 85-slot early ending; WT8 day13 MemS2 4b has 995 internal missing slots plus 411 at the tail; WT8 day14 LearnS2 4b has 1,753 internal missing slots plus 199 at the tail.

Recovery of preview freshness can be real even though previously lost samples remain absent. WT7 day14 Learn 4b has no missing slots despite a roughly 2.18-second delivery stall; this is an example of delayed delivery without permanent loss. The recorder's displayed FPS is (saved frames - 1) / elapsed camera time since the first saved frame. After losses stop, this cumulative average slowly approaches 40 Hz. Pure host buffering alone does not lower that camera-time-based average.

## GPIO

Eleven sessions have equal GPIO/1b counts and identical inferred trigger-slot patterns. Clock-rate-adjusted GPIO device times fit 1b camera times with maximum residuals below 2 ms. All 13 GPIO files contain only Data: 0 and have continuous sequence numbers. Continuous sequence numbers alone do not establish clean pulse timing.

- WT7 day13 Mem: 150,725 GPIO entries versus 150,721 frames. Rows 45,262-45,266 share one DeviceMs and PC receive time at 16:27:50.990. Excluding the four redundant rows 45,263-45,266 leaves 150,721 events; the maximum camera/device timing-fit residual becomes 0.616 ms.
- WT7 day14 Learn: 154,383 GPIO entries versus 227,103 frames. Row 43,288 is an off-cycle event splitting one normal 25-ms interval into 15 ms and 10 ms, at 10:49:14.217. Excluding it leaves 154,382 regular events; the maximum timing-fit residual becomes 0.784 ms. Logging then ends at 11:35:31.605, approximately 30 min 18 s before camera recording ends. Thus 72,721 subsequent 1b frames lack recorded regular GPIO events. The earlier raw count difference of 72,720 includes the extra event.

These exclusions were evaluated in memory only. Preserve original logs and retain excluded rows in a documented cleanup map if preparing downstream data. The absent GPIO tail cannot be called measured GPIO; camera-derived timing after that point must be labeled inferred.

## Recovery

Camera interval residuals from integer multiples of their fitted approximately 25-ms period are below 0.514 ms; all inferred trigger steps are positive. Full-session linear-grid residuals are at most 2.575 ms, well below half a frame (12.5 ms). This supports reliable identification of missing slots within each stream despite oscillator drift. It does not independently prove the first-frame offset between cameras.

Each *_preliminary_alignment.npz contains reference_saved_frame, trigger_index, and 1b_saved_frame/3b_saved_frame/4b_saved_frame/5b_saved_frame. Saved frame numbers are 1-based; zero means no image at that 1b time point. trigger_index is 0-based and retains gaps in 1b. These are preliminary maps, not rewritten videos. Source MP4 filenames are in audit.json.

For synchronized review, render each camera onto the 1b grid and insert conspicuous missing-image placeholders; if using repeated images, include a validity mask so repeats are never treated as measurements. Use trigger_index/40 for elapsed time so gaps in 1b are retained. Another option is the common intersection of valid frames, but keep original timestamps because removing missing positions compresses real time. Do not align by saved-frame number, stretch a whole video, or interpolate missing observations as if recorded.

## Likely causes and prevention

The strongest evidence points to an acquisition/transport backlog upstream of the video writer. Writer queue high-water marks are only 9-24 frames, and final writer/MP4 counts match acquisition metadata. This does not prove the encoder never imposed load, but there is no evidence of an encoder discarding these thousands of frames after they were logged.

3b and 5b are GigE cameras; their large-loss sessions have matching camera block-ID discontinuities for most missing slots. In WT8 day13 Learn, 5b also reports 526 failed grabs. 4b is USB, and its large timestamp gaps occur despite continuous block IDs and zero failed grabs. Therefore the existing failure counters alone miss substantial loss. No saved transport statistics distinguish packet loss, camera buffer overflow, host scheduling, and ignored triggers conclusively.

1. Move preview PNG encoding and filesystem writes out of the acquisition loop. SaveGuiPreviewFrame currently runs synchronously, including possible replace retries; during that work the grabber cannot retrieve the next frame. Use a separate worker with a bounded latest-image queue. Compare otherwise identical long recordings with GUI preview disabled to test this contribution.
2. Diagnose the actual link bottleneck with Basler stream statistics: missed frames, buffer underruns, failed buffers, resend counts, error text, and hardware frame-counter chunks where supported. Record cumulative missing trigger slots, recent FPS, arrival lag, and buffer occupancy during acquisition. Basler documents how these counters distinguish transport and buffer problems: [Stream grabber parameters](https://docs.baslerweb.com/stream-grabber-parameters).
3. For 3b/5b, verify one camera per dedicated GigE link or sufficient shared uplink capacity. Each 1920x1200 Mono8 stream at 40 Hz is 92.16 MB/s of image payload, before Ethernet overhead; two cannot share a 1-Gbps uplink. The current PC has two active 1-Gbps Intel I350 ports, which is consistent with separate links but does not prove the recording-time topology. Current PFS files use 1500-byte packets. Tune packet size, NIC receive buffers, and inter-packet delay together; enable jumbo frames only if the full path supports them. Avoid adding delay that reduces sustainable throughput below 40 Hz. See [Basler GigE troubleshooting](https://docs.baslerweb.com/knowledge/how-to-troubleshoot-lost-packets-or-frames-while-using-gige-cameras).
4. For 4b, inspect which USB controller is shared with 1b/2b and other high-bandwidth devices. Balance bandwidth or use a separate controller where needed; test cables and power. Basler's [Bandwidth Manager](https://docs.baslerweb.com/bandwidth-manager) allocates bandwidth per USB controller or network adapter. Current settings are not a historical snapshot of all settings used in these sessions.
5. Change stop/drain behavior to stop triggering first and then drain the camera/SDK queue until empty, with a monitored timeout based on backlog. Current acquisition has a default two-second post-stop drain limit. This is shorter than observed delivery delays and is a plausible explanation for the missing tails. Increasing that limit cannot restore frames already lost mid-session.
6. Monitor GPIO heartbeat, stale-log age, sequence continuity, and off-cycle events independently from camera status. Preserve raw data and flag suspected duplicate pulses rather than blindly deleting them. After a disconnect or restart, mark the unmeasured interval explicitly.

The 500-frame SDK buffer represents 12.5 seconds at 40 Hz. Increasing it may absorb short stalls but does not fix sustained throughput deficits and consumes about 1.15 GB per camera at this image size. Validate prevention changes with a long run covering the longest observed delay/loss onset, requiring no missing trigger slots and no growing delivery lag. No recording code, camera settings, or original recordings were changed by this audit.

## Artifacts

- camera_summary.csv: all counts, internal gaps, end deficits, clock-fit checks, delivery lag, and acquisition counters.
- gap_events.csv: every internal gap, adjacent saved-frame numbers, inferred trigger range, arrival times, and delivery lag.
- gpio_summary.csv / gpio_alignment_checks.csv: GPIO counts, sequence checks, endpoint comparison, and timing checks.
- audit.json: structured evidence including MP4 container metadata.
- timing_overview.png: cumulative losses and excess delivery lag for all sessions.
- *_preliminary_alignment.npz: per-session alignment maps described above.

Method note: 3b/4b/5b delivery lag is measured against interpolated 1b host elapsed time at the same inferred trigger, minus the initial median offset. It is a relative delivery metric, not absolute exposure-to-host latency. 1b uses its own camera/host clock baseline. Tail deficits assume common trigger start. Full MP4 decoding and visual offset verification remain outside this metadata audit.