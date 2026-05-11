# Change Log From Base Campy Code

This file tracks local modifications made on top of the original `campy` codebase in this workspace.

## 2026-04-03

### Dependency metadata
- Added `imageio-ffmpeg` to `install_requires` in `setup.py`.
- Reason: `campy/writer.py` imports `imageio_ffmpeg.write_frames`, but the dependency was not declared in the original package metadata.

### Basler external-trigger stability
- Updated `campy/cameras/basler.py` so `GrabFrame()` uses `camera.RetrieveResult(100, pylon.TimeoutHandling_ThrowException)` instead of `RetrieveResult(0, ...)`.
- Reason: a zero-millisecond timeout causes immediate timeout exceptions during externally triggered acquisition because the code polls faster than the trigger period.
- Goal: improve compatibility with low-rate external triggering such as 40 Hz hardware-triggered Basler capture.

### Deterministic Basler camera mapping
- Updated `campy/configurator.py` to support optional `cameraSerialNo` config values for deterministic device selection by serial number instead of relying only on device enumeration order.
- Added startup logging that prints each configured camera name, resolved device index, actual serial number, and assigned settings file.
- Reason: multi-camera Basler discovery order can differ from physical Ethernet port order, which can silently apply the wrong `.pfs` file to a camera.

### Basler timeout log suppression
- Updated `campy/cameras/unicam.py` to suppress repeated Basler `Grab timed out` exceptions during the grab loop.
- Reason: in externally triggered acquisition, polling can legitimately occur between trigger arrivals, and the original behavior flooded logs with noisy timeout errors.

### External-trigger preview and timeout tuning
- Added configurable `grabTimeoutInMs` support in `campy/configurator.py` and `campy/cameras/basler.py`.
- Switched Basler preview to a generic NumPy/matplotlib display path instead of the Pylon image window so preview can be re-enabled with `displayFrameRate > 0` while keeping the run headless-capable when set to `0`.
- Added `timeoutCount` and `otherErrorCount` to saved metadata in `campy/cameras/unicam.py`.
- Reason: external-triggered runs benefit from a longer configurable wait for the next trigger, and preview should be adjustable without reopening Pylon-style windows.

### Triggered-run diagnostics and stopping behavior
- Added Basler `FrameID` logging via `GrabResult.GetBlockID()` in `campy/cameras/basler.py`.
- Updated `campy/cameras/unicam.py` to save:
  - `frameNumber`
  - `frameID`
  - camera timestamp
  - host receive timestamp
  into `frametimes.npy`, `frametimes.mat`, and a new `frame_metadata.csv`.
- Added summary counters for:
  - `frameIdGapCount`
  - `framesQueued`
  - `queueHighWaterMark`
  - `timeoutCount`
  - `otherErrorCount`
- Updated externally triggered runs to stop by elapsed host time from the first received frame instead of waiting for every camera to reach the same saved frame count.
- Updated `campy/writer.py` to save `writer_stats.csv` with the final `framesWritten` count after the queue is fully drained.
- Reason: distinguish camera/frame-ID progression from host-side grab/write behavior and avoid misleading multi-camera runs where different cameras finish at different wall-clock times while chasing equal saved frame counts.

### Failed-grab diagnostics for stressed Basler runs
- Added `GrabSucceeded()` handling for Basler grab results.
- Updated `campy/cameras/unicam.py` to count `failedGrabCount` and treat repeated `Pixel format currently not supported` exceptions as failed grab results instead of noisy generic errors.
- Added `failedGrabCount` to `metadata.csv`.
- Reason: at higher-load runs (for example 40 Hz), some Basler results appear to arrive in a bad/incomplete state; these should be counted explicitly as acquisition failures rather than spam the log.

### Local test config
- Added `configs/campy_config_1cam_basler_exttrigger_40hz.yaml`.
- Reason: provide a conservative one-camera validation config for Basler GigE external-trigger testing with an existing `.pfs` file.
