"""Small recording-side workers. No hardware is opened by this module.

Legacy result schemas are unchanged. Additional telemetry lives in separate files.
"""
import csv
import json
import logging
import math
import os
import threading
import time
from collections import deque
from pathlib import Path

import yaml

FRAME_HEADER = ['savedFrameNumber', 'cameraFrameID', 'cameraTimeStampSec',
                'hostTimeStampSec', 'hostDateTimeIso', 'hostDateTimeEpochSec']


def atomic_json(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(data, f, allow_nan=False)
    os.replace(str(temp), str(path))


class LatestWorker:
    """One active job and one latest pending job; producer never waits for I/O."""
    def __init__(self, callback, rate):
        self.callback = callback
        self.interval = 1.0 / max(float(rate), 1.0)
        self.pending = deque(maxlen=1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, item):
        self.pending.append(item)

    def _run(self):
        while not self.stop.is_set():
            started = time.monotonic()
            try:
                item = self.pending.popleft()
            except IndexError:
                item = None
            if item is not None:
                try:
                    self.callback(item)
                except Exception:
                    logging.exception('Preview worker failed')
            self.stop.wait(max(.001, self.interval - (time.monotonic() - started)))

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1.0)


class MetadataJournal:
    """Append compatible rows off the acquisition thread; flush even during stalls.

    Flush is not fsync: this protects against process termination, not power loss.
    The queue contains only small metadata rows, never image data.
    """
    def __init__(self, folder, flush_interval=1.0):
        Path(folder).mkdir(parents=True, exist_ok=True)
        self.path = Path(folder) / 'frame_metadata.csv'
        self.file = self.path.open('w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(FRAME_HEADER)
        self.file.flush()
        self.rows = deque()
        self.error = None
        self.stop = threading.Event()
        self.interval = max(.05, float(flush_interval))
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def append(self, row):
        if self.error is not None:
            raise RuntimeError('Metadata journal failed: {}'.format(self.error))
        self.rows.append(tuple(row))

    def _run(self):
        deadline = time.monotonic() + self.interval
        try:
            while not self.stop.is_set() or self.rows:
                # Bounded batches ensure flush deadlines are checked under load.
                for _ in range(256):
                    try:
                        row = self.rows.popleft()
                    except IndexError:
                        break
                    self.writer.writerow(row)
                if time.monotonic() >= deadline:
                    self.file.flush()
                    deadline = time.monotonic() + self.interval
                if not self.rows:
                    self.stop.wait(.02)
            self.file.flush()
        except Exception as exc:
            self.error = exc
            logging.exception('Incremental metadata write failed')
        finally:
            self.file.close()

    def close(self, timeout=10.0):
        self.stop.set()
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise RuntimeError('Metadata journal is still draining')
        if self.error:
            raise RuntimeError('Metadata journal failed: {}'.format(self.error))


class RuntimeStatus:
    """Publish telemetry and read controls away from acquisition.

    Only the acquisition thread calls camera APIs. Control requests are latest-only.
    Lag is a relative estimate, not absolute sensor-to-host latency.
    """
    def __init__(self, params):
        self.params = params
        self.folder = Path(params['saveFolder']) / params['cameraName']
        self.folder.mkdir(parents=True, exist_ok=True)
        self.snapshot = {}
        self.request = None
        self.control_mtime = None
        self.exposure = dict(appliedExposureUs=params.get('appliedExposureTimeInUs',
                             params.get('cameraExposureTimeInUs')), exposureState='idle')
        self.last_apply = float('-inf')
        self.last_attempt = None
        self.control_events = deque()
        self.period = 1.0 / float(params['frameRate'])
        self.first = None
        self.previous = None
        self.missing = 0
        self.baseline = 0.0
        self.samples = deque(maxlen=512)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def observe(self, count, camera_time, host_time, epoch, queue_size):
        if self.first is None:
            self.first = (camera_time, host_time)
        if self.previous is not None:
            dt = camera_time - self.previous[0]
            self.missing += max(0, int(round(dt / self.period)) - 1)
        cam_elapsed = camera_time - self.first[0]
        host_elapsed = host_time - self.first[1]
        raw_lag = host_elapsed - cam_elapsed
        # Allow up to 200 ppm baseline drift, without following second-scale stalls.
        host_step = max(0.0, host_time - self.previous[1]) if self.previous else 0.0
        self.baseline = min(raw_lag, self.baseline + .0002 * host_step)
        lag = max(0.0, raw_lag - self.baseline)
        self.previous = (camera_time, host_time)
        self.samples.append((host_time, count))
        while len(self.samples) > 2 and self.samples[1][0] < host_time - 2.0:
            self.samples.popleft()
        elapsed = host_time - self.samples[0][0]
        recent = (count - self.samples[0][1]) / elapsed if elapsed > 0 else 0.0
        self.snapshot = dict(cameraName=self.params['cameraName'], framesCollected=count,
            fps=(count-1)/cam_elapsed if cam_elapsed > 0 else 0.0,
            elapsedSec=cam_elapsed, updatedEpochSec=epoch, recentRateHz=recent,
            deliveryLagEstimateSec=lag, missingSlotCount=self.missing,
            writerQueueFrames=queue_size, acquisitionMonotonic=time.monotonic())

    def _read_control(self):
        path = self.params.get('guiCameraControlFile')
        if not path or path == 'None':
            return
        try:
            stamp = Path(path).stat().st_mtime_ns
            if stamp == self.control_mtime:
                return
            with open(path, encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            camera_control = data.get('cameras', {}).get(self.params['cameraName'], {})
            value = camera_control.get('cameraExposureTimeInUs', data.get('cameraExposureTimeInUs'))
            if value is not None:
                value = float(value)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError('Invalid exposure request')
                self.request = (value, camera_control.get('requestedAtEpochSec',
                               data.get('updatedAtEpochSec', stamp)))
            self.control_mtime = stamp
        except FileNotFoundError:
            pass
        except Exception:
            logging.exception('Could not read exposure request')

    def apply_pending(self, cam, camera, stopping=False):
        request = self.request
        if request is None or request == self.last_attempt or stopping:
            return
        value, token = request
        applied = float(self.exposure.get('appliedExposureUs') or 0)
        if abs(value-applied) < .5:
            self.last_attempt = request
            self.exposure = dict(self.exposure, exposureState='idle')
            return
        if time.monotonic()-self.last_apply < max(0.0, float(self.params.get('exposureAdjustmentIntervalSec',1.0))):
            return
        snap = self.snapshot
        if snap.get('deliveryLagEstimateSec', 0) > float(self.params.get('exposureBacklogThresholdSec', .25)):
            self.exposure = dict(self.exposure, exposureState='deferred: backlog')
            return
        # No simultaneous SDK access: a separate Python thread cannot guarantee
        # RetrieveResult is independent of node writes / SDK locks.
        started = time.monotonic()
        started_epoch = time.time()
        self.exposure = dict(self.exposure, exposureState='applying', exposureError='',
                             exposureApplyStartedEpochSec=started_epoch)
        error = ''
        try:
            if not hasattr(cam, 'ApplyRuntimeControls'):
                raise RuntimeError('Camera backend does not support exposure control')
            cam.ApplyRuntimeControls(camera, self.params, {'cameraExposureTimeInUs': value})
            self.exposure = dict(self.exposure, appliedExposureUs=self.params.get('appliedExposureTimeInUs'),
                                 exposureState='idle')
        except Exception as exc:
            error = str(exc)
            self.exposure = dict(self.exposure, exposureState='failed', exposureError=error)
            logging.exception('Exposure change failed')
        finally:
            self.last_apply = time.monotonic()
            self.last_attempt = request
            self.exposure = dict(self.exposure, exposureApplyDurationSec=self.last_apply-started,
                                 exposureCompletedEpochSec=time.time(), exposureRequestToken=token)
            self.control_events.append(dict(self.exposure, requestedExposureUs=value,
                frameBeforeApply=self.snapshot.get('framesCollected',0)))

    def _publish(self, history):
        data = dict(self.snapshot)
        data.pop('acquisitionMonotonic', None)
        data.update(self.exposure)
        data['publishedEpochSec'] = time.time()
        if self.request:
            value, token = self.request
            if self.request != self.last_attempt:
                data['pendingExposureUs'] = value
                if data['exposureState'] == 'idle':
                    data['exposureState'] = 'pending'
        atomic_json(self.folder/'acquisition_status.json', data)
        history.write(json.dumps(data, allow_nan=False)+'\n')
        history.flush()
        if self.snapshot:
            fields = ['cameraName','framesCollected','fps','elapsedSec','updatedEpochSec']
            path = self.folder/'live_status.csv'
            temp = path.with_name(path.name+'.tmp')
            with temp.open('w',newline='') as f:
                w=csv.writer(f); w.writerow(fields)
                w.writerow([data[k] for k in fields])
            os.replace(str(temp),str(path))

    def _run(self):
        try:
            with (self.folder/'acquisition_diagnostics.jsonl').open('a',encoding='utf-8') as history, \
                    (self.folder/'exposure_changes.jsonl').open('a',encoding='utf-8') as changes:
                deadline = 0.0
                while not self.stop.is_set():
                    self._read_control()
                    self._flush_changes(changes)
                    if time.monotonic() >= deadline:
                        try:
                            self._publish(history)
                        except Exception:
                            logging.exception('Status write failed')
                        deadline = time.monotonic()+1.0
                    self.stop.wait(.1)
                self._flush_changes(changes)
                self._publish(history)
        except Exception:
            logging.exception('Status worker stopped')

    def _flush_changes(self, handle):
        wrote = False
        while self.control_events:
            handle.write(json.dumps(self.control_events.popleft(), allow_nan=False)+'\n')
            wrote = True
        if wrote:
            handle.flush()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2.0)


def bounded_call(label, callback, timeout=3.0):
    """Keep a broken device's cleanup from preventing other devices' cleanup."""
    errors = []
    def invoke():
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)
    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    worker.join(timeout=max(0.0, timeout))
    if worker.is_alive():
        logging.error('%s timed out; device state is unknown', label)
        return False
    if errors:
        logging.error('%s failed: %s', label, errors[0])
        return False
    return True
