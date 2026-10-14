# Recording reliability revision

This revision changes acquisition support work and shutdown handling without
rewriting existing sessions. Use it for a new recording after the current GUI and
recording have finished. Do not restart a running experiment to load this revision.

## Output compatibility

The following legacy outputs retain their names and schemas:

- `frame_metadata.csv`: six columns in the original order, saved frame numbering
  starting at 1, camera and monotonic host timestamps relative to their first
  acquired frame, original ISO/epoch host arrival times.
- `frametimes.npy`: the original 6-by-N object array.
- `frametimes.mat`: the original six MATLAB variables.
- `metadata.csv` and `writer_stats.csv`: the original key/value CSV format.
- `live_status.csv`: the original five columns.
- Video naming, encoding settings, and configured recording frame rate are unchanged.

`frame_metadata.csv` is now appended by a metadata worker during acquisition and
flushed approximately once per second, including while acquisition is stalled.
Rows still describe acquired/queued frames, not independently verified encoded
frames. The writer count must still be checked after abnormal termination.
Normal shutdown writes the legacy NPY/MAT exports and final parameter metadata
before attempting hardware close. Each export is attempted independently.

A hard process kill can lose the newest unflushed rows and may prevent NPY/MAT
exports and MP4 finalization. Flush does not provide a power-loss guarantee.
The revision preserves a partial CSV; it does not automatically repair MP4s or
reconstruct missing images. Previously recorded files are not migrated.

Additional information is stored separately per camera:

- `acquisition_status.json`: latest metrics and applied/pending exposure status.
- `acquisition_diagnostics.jsonl`: approximately one status sample per second.
- `exposure_changes.jsonl`: individual exposure attempts, API duration, result,
  requested/applied values, and the saved frame before each attempt. This is not
  a claim about the precise first sensor frame affected by the change.
- `transport_diagnostics.json`: supported Basler stream counters collected before
  closing the stream. Unsupported counters are omitted. No new chunk modes are enabled.

## Preview

GUI preview PNG encoding and file writes run in a separate thread per camera.
There is one pending latest-image slot; preview work never queues all images or
waits for the writer. Recording retains its independent image queue.
The Basler array path uses the existing owned image copy; no zero-copy result
buffer is handed to the preview worker.

At a recording rate of 40 Hz and configured preview rate of 20 Hz, every second
acquired frame is eligible for preview. The worker is capped at 20 updates/sec
of host time, so catching up a camera backlog does not cause a PNG burst.
The GUI also polls at 50 ms, removing the prior 10 Hz producer / 5 Hz GUI limits.
This is a target, not a real-time delivery guarantee. The existing frame-stride
scheduler quantizes other requested rates to acquisition-frame intervals.

The GUI no longer recounts the growing frame CSV every refresh while recording.
This avoids increasing GUI/disk work as the session gets longer.

## Exposure control

Control-file reads/parsing occur in the status worker; GUI updates replace the
control file atomically. Each camera retains only its latest pending request.
An actual SDK update is performed by the camera-owning acquisition thread,
after the current grab result is released:

- At least 1 second after the previous attempt completes, by default.
- Deferred while the estimated delivery lag is above 0.25 seconds.
- No new updates during stop/drain.
- Failed requests are reported, not automatically retried forever. Applying a
  new request explicitly permits another attempt.
- The applied exposure is read back from the camera node.

**Exposure SDK calls are deliberately not issued concurrently with retrieval.**
Basler documents locking in `CInstantCamera`; it does not establish that moving a
parameter write to another Python thread makes retrieval nonblocking. Therefore
one slow SDK call can still delay acquisition. The duration/event logs allow this
to be measured before introducing a different hardware-control architecture.
See [Basler CInstantCamera reference](https://docs.baslerweb.com/pylonapi/cpp/class_pylon_1_1_c_instant_camera).

No automatic multi-step exposure transitions are introduced. Live exposure
changes remain available, subject to the interval and backlog checks.

## Monitoring and stop

Status age is based on the last acquired frame, not merely a worker heartbeat.
The recent rate uses an approximately two-second host-time window; the GUI shows
zero recent rate and Stale when no frame update has arrived for over 2.5 seconds.
Missing slots are estimated from adjacent camera timestamps and the target period.
Delivery lag is a relative estimate using host/camera elapsed time, with a slowly
moving baseline allowing small clock drift. It is not absolute exposure latency
and is not suitable as a replacement for offline clock fitting or alignment.

Stopping attempts trigger shutdown with a bounded wait, then signals cameras to
drain. Cameras retrieve remaining results until a retrieval timeout, subject to
a 30-second default drain limit. Failure to stop the trigger can therefore end in
a drain-limit warning; physical trigger state cannot be guaranteed after a device
timeout. A timed-out trigger stop is not followed by concurrent close commands to
the same controller.

The image writer drains its queue, and the camera process waits for the metadata
finalizer. Camera/system/device cleanup failures are isolated. The GUI no longer
automatically interrupts after 20 seconds and terminates 12 seconds later; it
reports a pending stop instead. A truly hung driver or disk may still require
operator intervention. No watchdog can guarantee safe completion of a blocked
native SDK call.

Optional YAML/CLI settings (no existing configuration was edited):

| Setting | Default |
|---|---:|
| `metadataFlushIntervalSec` | 1.0 |
| `exposureAdjustmentIntervalSec` | 1.0 |
| `exposureBacklogThresholdSec` | 0.25 |
| `postStopDrainSec` | 30.0 |
| `triggerStopTimeoutSec` | 3.0 |

## Validation

Startup fixes: the video writer creates its output directory with `exist_ok=True`
because the metadata journal may create the same directory concurrently. Start
input is polled without a daemon `input()` thread, so cancelling preparation or
encountering a worker failure while the GUI stdin pipe remains open does not leave
a buffered stdin lock held during interpreter shutdown. Preparation also checks
the shared worker stop event. Existing configurations and output schemas are unchanged.
Hardware-free startup regressions cover concurrent directory creation, preservation
of an existing metadata file, a conflicting file path, GUI Enter, EOF, and cancellation
with the stdin pipe still open.

Hardware-free tests run with:

```powershell
& 'C:\Users\Cornell\anaconda3\envs\campy\python.exe' -B -m unittest discover -s tests -v
```

Tests cover partial CSV survival after killing a test-owned subprocess, legacy
CSV/NPY/MAT/parameter compatibility, latest-only preview, exposure interval and
backlog behavior, failed exposure handling, metadata export failures, close and
trigger-stop failures, buffer drain beyond two seconds, consistent image/metadata
commit when extraction fails, encoder failure, GUI rate configuration, and metrics.

No connected camera, PulsePal, current recording, or existing data was used for
these tests. Real 20 Hz preview performance, CPU/GPU load, transport counters, and
exposure API latency require a subsequent hardware test. Compare fixed exposure
and deliberate interval-limited changes, monitor lag/missing slots, and include a
long run because prior failures sometimes appeared tens of minutes into a session.
Compare final MP4 counts with CSV/NPY/MAT/writer counts using the existing analysis
code. GPIO monitoring and existing-video alignment are outside this revision.
