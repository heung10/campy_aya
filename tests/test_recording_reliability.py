"""Hardware-free regression tests. All recording outputs use temporary directories."""
import copy
import csv
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import numpy as np

from campy.cameras import unicam
from campy.recording_runtime import MetadataJournal, LatestWorker, RuntimeStatus, FRAME_HEADER, bounded_call
from campy import writer


def params(folder):
    return dict(saveFolder=str(folder), cameraName='1b', frameRate=40,
        displayFrameRate=0, guiPreviewEnabled=False, guiPreviewFrameRate=20,
        displayDownsample=2, chunkLengthInSec=5, recTimeInSec=.075,
        infiniteRecording=False, cameraTrigger='Software', cameraMake='basler',
        cameraDebug=True, cameraExposureTimeInUs=1000, appliedExposureTimeInUs=1000,
        cameraModel='test', cameraSerialNo='test')


class FakeCamera:
    def __init__(self, p, stop=None, fail_close=False, bad_frame=None):
        self.p = p
        self.index = 0
        self.released = []
        self.stop = stop
        self.fail_close = fail_close
        self.bad_frame = bad_frame

    def OpenCamera(self, p):
        return self, p

    def StartGrabbing(self, camera):
        return True

    def GrabFrame(self, camera, number, p):
        if self.stop:
            self.stop.set()
            if self.index >= 8:
                raise RuntimeError('Grab timed out')
        self.index += 1
        return self.index

    def GrabSucceeded(self, result):
        return True

    def GetImageArray(self, result):
        return np.full((2,2), result, dtype=np.uint8)

    def GetTimeStamp(self, result):
        if result == self.bad_frame:
            raise RuntimeError('Broken frame timestamp')
        return 100+result*.025

    def GetFrameID(self, result):
        return result-1

    def ReleaseFrame(self, result):
        self.released.append(result)

    def CloseCamera(self, p, camera):
        assert (Path(p['saveFolder'])/'1b/frametimes.npy').exists()
        if self.fail_close:
            raise RuntimeError('Simulated close failure')


class RecordingTests(unittest.TestCase):
    def test_incremental_flush_during_frame_stall(self):
        with tempfile.TemporaryDirectory() as d:
            journal = MetadataJournal(d, .05)
            row = [1,0,0.0,0.0,'2026-10-07T10:00:00.000000','1791381600.000000']
            journal.append(row)
            deadline = time.monotonic()+2
            while time.monotonic()<deadline:
                with journal.path.open() as f:
                    rows=list(csv.reader(f))
                if len(rows)==2:
                    break
                time.sleep(.02)
            self.assertEqual(rows[0], FRAME_HEADER)
            self.assertEqual(rows[1], list(map(str,row)))
            journal.close()

    def test_flushed_csv_survives_process_termination(self):
        with tempfile.TemporaryDirectory() as d:
            code = ('import time; from campy.recording_runtime import MetadataJournal; '
                    'j=MetadataJournal({!r},.05); j.append([1,0,0.,0.,"iso","epoch"]); '
                    'time.sleep(.2); print("flushed",flush=True); time.sleep(30)').format(d)
            child = subprocess.Popen([sys.executable,'-B','-c',code],stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(),'flushed')
                child.terminate()  # Only this test-owned child, never a recording process.
                child.wait(timeout=5)
                with (Path(d)/'frame_metadata.csv').open() as f:
                    self.assertEqual(len(list(csv.reader(f))),2)
            finally:
                if child.poll() is None:
                    child.kill(); child.wait()
                child.stdout.close()

    def test_preview_latest_only_and_nonblocking(self):
        entered=threading.Event(); release=threading.Event(); seen=[]
        def callback(item):
            seen.append(item)
            if item==1:
                entered.set(); release.wait(2)
        worker=LatestWorker(callback,100)
        try:
            worker.submit(1); self.assertTrue(entered.wait(1))
            for item in range(2,101): worker.submit(item)
            self.assertEqual(list(worker.pending),[100])
            release.set()
            deadline=time.monotonic()+1
            while len(seen)<2 and time.monotonic()<deadline: time.sleep(.01)
            self.assertEqual(seen,[1,100])
        finally:
            release.set(); worker.close()

    def test_exposure_interval_latest_request_and_backlog(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d); runtime=RuntimeStatus(p); runtime.close()
            calls=[]
            class Backend:
                @staticmethod
                def ApplyRuntimeControls(camera,p,control):
                    value=control['cameraExposureTimeInUs']; calls.append(value)
                    p['appliedExposureTimeInUs']=value
            with patch('campy.recording_runtime.time.monotonic',return_value=10):
                runtime.request=(2000,1); runtime.apply_pending(Backend,None)
            with patch('campy.recording_runtime.time.monotonic',return_value=10.5):
                runtime.request=(3000,2); runtime.apply_pending(Backend,None)
                runtime.request=(4000,3); runtime.apply_pending(Backend,None)
            self.assertEqual(calls,[2000])
            with patch('campy.recording_runtime.time.monotonic',return_value=11):
                runtime.snapshot={'deliveryLagEstimateSec':1}
                runtime.apply_pending(Backend,None)
                self.assertEqual(calls,[2000])
                runtime.snapshot={'deliveryLagEstimateSec':0}
                runtime.apply_pending(Backend,None)
            self.assertEqual(calls,[2000,4000])
            runtime.request=(5000,4)
            runtime.apply_pending(Backend,None,stopping=True)
            self.assertEqual(calls,[2000,4000])

    def test_failed_exposure_is_not_retried_forever(self):
        with tempfile.TemporaryDirectory() as d:
            r=RuntimeStatus(params(d)); r.close(); r.request=(2000,1)
            backend=types.SimpleNamespace(ApplyRuntimeControls=lambda *args: (_ for _ in ()).throw(RuntimeError('device timeout')))
            r.apply_pending(backend,None)
            self.assertEqual(r.exposure['exposureState'],'failed')
            with patch.object(backend,'ApplyRuntimeControls') as call:
                r.apply_pending(backend,None)
                call.assert_not_called()

    def test_capture_saves_before_failing_camera_close(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d); backend=FakeCamera(p,fail_close=True)
            images=deque(); stopped=deque()
            with patch.object(unicam,'ImportCam',return_value=backend):
                unicam.GrabFrames(p,images,deque(),deque(),stopped)
            self.assertEqual(len(images),3)
            self.assertTrue(stopped)
            with (Path(d)/'1b/frame_metadata.csv').open() as f: rows=list(csv.reader(f))
            self.assertEqual(len(rows),4)
            a=np.load(str(Path(d)/'1b/frametimes.npy'),allow_pickle=True)
            self.assertEqual(a.shape,(6,3))
            self.assertEqual(float(rows[1][2]),0)
            self.assertEqual(float(rows[1][3]),0)
            self.assertEqual(backend.released,[1,2,3])

    def test_drain_continues_beyond_old_two_second_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d); stop=threading.Event(); backend=FakeCamera(p,stop=stop)
            images=deque(); clock=iter(np.arange(100,200,.4))
            with patch.object(unicam,'ImportCam',return_value=backend), patch.object(unicam.time,'perf_counter',side_effect=lambda:next(clock)):
                unicam.GrabFrames(p,images,deque(),deque(),deque(),stopEvent=stop)
            self.assertEqual(len(images),8)

    def test_partial_frame_failure_does_not_desynchronize_rows_and_images(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d); backend=FakeCamera(p,bad_frame=2); images=deque()
            with patch.object(unicam,'ImportCam',return_value=backend):
                unicam.GrabFrames(p,images,deque(),deque(),deque())
            a=np.load(str(Path(d)/'1b/frametimes.npy'),allow_pickle=True)
            self.assertEqual(list(a[1]),[0,2,3])
            self.assertEqual([int(x[0,0])-1 for x in images],list(a[1]))
            self.assertEqual(backend.released,[1,2,3,4])

    def test_legacy_csv_npy_mat_compatibility(self):
        original=subprocess.check_output(['git','show','HEAD:campy/cameras/unicam.py'],text=True)
        legacy=types.ModuleType('legacy_unicam'); exec(compile(original,'legacy_unicam','exec'),legacy.__dict__)
        with tempfile.TemporaryDirectory() as d:
            old=Path(d)/'old'; new=Path(d)/'new'
            (old/'1b').mkdir(parents=True); (new/'1b').mkdir(parents=True)
            g=unicam.GrabData(params(d))
            g.update(frameNumber=[1,2,3],frameID=[0,1,3],timeStamp=[12.,12.025,12.075],
                hostTimeStamp=[50.,50.026,50.078],hostDateTimeIso=['a','b','c'],
                hostDateTimeEpochSec=['100.000000','100.026000','100.078000'])
            legacy.SaveMetadata(params(old),copy.deepcopy(g))
            unicam.SaveMetadata(params(new),copy.deepcopy(g))
            self.assertEqual((old/'1b/frame_metadata.csv').read_bytes(),(new/'1b/frame_metadata.csv').read_bytes())
            a=np.load(str(old/'1b/frametimes.npy'),allow_pickle=True)
            b=np.load(str(new/'1b/frametimes.npy'),allow_pickle=True)
            np.testing.assert_array_equal(a,b)
            with (old/'1b/metadata.csv').open() as f: old_meta=dict(csv.reader(f))
            with (new/'1b/metadata.csv').open() as f: new_meta=dict(csv.reader(f))
            old_meta.pop('saveFolder'); new_meta.pop('saveFolder')
            self.assertEqual(old_meta,new_meta)
            if unicam.sio:
                a=unicam.sio.loadmat(str(old/'1b/frametimes.mat'))
                b=unicam.sio.loadmat(str(new/'1b/frametimes.mat'))
                for key in ['frameNumber','frameID','timeStamp','hostTimeStamp','hostDateTimeIso','hostDateTimeEpochSec']:
                    np.testing.assert_array_equal(a[key],b[key])

    def test_bounded_device_failure_does_not_block_caller(self):
        release=threading.Event()
        try:
            self.assertFalse(bounded_call('fake stuck device',lambda:release.wait(2),.02))
            self.assertFalse(bounded_call('fake failed device',lambda:1/0,.1))
        finally: release.set()

    def test_writer_failure_preserves_stats_and_stops_producer(self):
        class Sink:
            def send(self,img): raise RuntimeError('encoder failed')
            def close(self): raise RuntimeError('encoder close failed')
        with tempfile.TemporaryDirectory() as d:
            p=params(d); stop=deque(); old=signal.getsignal(signal.SIGINT)
            try:
                with patch.object(writer,'OpenWriter',return_value=(Sink(),True,{'queue':stop,'message':'STOP'})):
                    with self.assertRaises(RuntimeError): writer.WriteFrames(p,deque([1]),stop,deque())
            finally: signal.signal(signal.SIGINT,old)
            self.assertTrue(stop)
            with (Path(d)/'1b/writer_stats.csv').open() as f:
                self.assertEqual(next(csv.reader(f)),['framesWritten','0'])

    def test_status_does_not_scan_growing_metadata(self):
        from campy.gui import status
        with tempfile.TemporaryDirectory() as d:
            camera=Path(d)/'1b'; camera.mkdir()
            (camera/'acquisition_status.json').write_text(json.dumps(dict(framesCollected=100,
                updatedEpochSec=time.time()-5, recentRateHz=40, fps=40, missingSlotCount=2)))
            with patch.object(status,'_csv_data_rows',side_effect=AssertionError('CSV scan')):
                row,_=status._camera_status('1b',Path(d),40,'recording')
            self.assertEqual(row.state,'Stale')
            self.assertIn('0.0 Hz recent',row.rate)
            self.assertIn('missing slots 2',row.notes)

    def test_empty_recording_still_exports_legacy_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d)
            unicam.SaveMetadata(p,unicam.GrabData(p))
            a=np.load(str(Path(d)/'1b/frametimes.npy'),allow_pickle=True)
            self.assertEqual(a.shape,(6,0))
            with (Path(d)/'1b/frame_metadata.csv').open() as f:
                self.assertEqual(list(csv.reader(f)),[FRAME_HEADER])

    def test_initial_parameter_snapshot_does_not_mark_ready_camera_saved(self):
        from campy.gui import status
        with tempfile.TemporaryDirectory() as d:
            p=params(d)
            unicam.SaveParameterMetadata(p,unicam.GrabData(p))
            row,_=status._camera_status('1b',Path(d),40,'ready')
            self.assertEqual(row.state,'Ready')

    def test_metrics_distinguish_missing_slot_from_catchup(self):
        with tempfile.TemporaryDirectory() as d:
            r=RuntimeStatus(params(d)); r.close()
            r.observe(1,100,500,1000,0)
            r.observe(2,100.025,500.525,1000.525,0)
            self.assertGreater(r.snapshot['deliveryLagEstimateSec'],.49)
            r.observe(3,100.075,500.526,1000.526,0)
            self.assertEqual(r.snapshot['missingSlotCount'],1)
            for i in range(4,41):
                cam_elapsed=i*.025
                host_elapsed=max(.526+(i-3)*.001,cam_elapsed)
                r.observe(i,100+cam_elapsed,500+host_elapsed,1000+host_elapsed,0)
            self.assertEqual(r.snapshot['missingSlotCount'],1)
            self.assertLess(r.snapshot['deliveryLagEstimateSec'],.001)

    def test_export_failure_does_not_prevent_other_formats(self):
        with tempfile.TemporaryDirectory() as d:
            p=params(d)
            with patch.object(unicam.np,'save',side_effect=OSError('simulated npy failure')):
                unicam.SaveMetadata(p,unicam.GrabData(p))
            self.assertTrue((Path(d)/'1b/frame_metadata.csv').exists())
            self.assertTrue((Path(d)/'1b/metadata.csv').exists())
            if unicam.sio:self.assertTrue((Path(d)/'1b/frametimes.mat').exists())

    def test_trigger_stop_timeout_still_signals_cameras(self):
        # Load function definitions without campy.py's hardware-opening footer.
        source=Path('campy/campy.py').read_text().split('# Open systems, creates global')[0]
        module=types.ModuleType('test_campy'); exec(compile(source,'test_campy','exec'),module.__dict__)
        stop=threading.Event(); start=threading.Event(); release=threading.Event()
        systems={}; p=params('unused'); p.update(triggerController='pulsepal',pulseFrequencyHz=40,triggerStopTimeoutSec=.01)
        try:
            with patch.object(module.trigger,'StopTriggerOutputs',side_effect=lambda *a:release.wait(2)) as call:
                module.StopSynchronizedTrigger(systems,p,stop,start)
                self.assertTrue(stop.is_set()); self.assertTrue(start.is_set())
                self.assertFalse(systems['_triggerStopSucceeded'])
                module.StopSynchronizedTrigger(systems,p,stop,start)
                self.assertEqual(call.call_count,1)
        finally: release.set()

    def test_gui_preview_rate_and_runtime_exposure(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PyQt5.QtWidgets import QApplication
        from campy.gui.preview_tab import PreviewTab
        from campy.gui.live_tab import LiveTab
        from campy.gui.process_runner import AcquisitionRunner
        import yaml
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as d:
            p=params(d); p.update(numCams=1,cameraNames=['1b'],displayFrameRate=20)
            config=Path(d)/'config.yaml'; config.write_text(yaml.safe_dump(p))
            runner=AcquisitionRunner()
            with patch('tempfile.tempdir',d):
                runtime=runner._make_runtime_config(str(config))
            data=yaml.safe_load(Path(runtime).read_text())
            self.assertEqual(data['guiPreviewFrameRate'],20)
            self.assertEqual(data['displayFrameRate'],0)
            preview=PreviewTab(); preview.set_config(p)
            self.assertEqual(preview.preview_timer.interval(),50)
            live=LiveTab(); live.set_config(p,str(config))
            with patch.object(runner,'is_running',return_value=True):
                runner.apply_exposure_time('1b',2200)
                runner.apply_exposure_time('1b',3300)
            request=yaml.safe_load(Path(runner._camera_control_file_path).read_text())
            self.assertEqual(request['cameras']['1b']['cameraExposureTimeInUs'],3300)
            self.assertIn('requestedAtEpochSec',request['cameras']['1b'])
            runner._cleanup_runtime_config()
            preview.preview_timer.stop(); live.refresh_timer.stop()
            preview.close(); live.close()
        app.processEvents()


if __name__=='__main__':
    unittest.main()
