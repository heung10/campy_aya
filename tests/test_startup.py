"""Startup regressions: no camera, encoder, or existing recording is opened."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from campy import writer


class StartupTests(unittest.TestCase):
    def test_metadata_creates_directory_just_before_writer(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'cam3'
            original_makedirs = os.makedirs

            def concurrent_create(path, **kwargs):
                # Deterministically reproduce the other thread winning the race.
                original_makedirs(path, exist_ok=True)
                (folder / 'frame_metadata.csv').write_text('preserve me')
                return original_makedirs(path, **kwargs)

            p = dict(saveFolder=root, cameraName='cam3', videoFilename='test.mp4',
                     pixelFormatInput='gray', pixelFormatOutput='yuv420p',
                     codec='h264', quality=20, preset='None', frameRate=40,
                     gpuID=-1, frameWidth=2, frameHeight=2, ffmpegLogLevel='warning')
            with patch.object(writer.os, 'makedirs', side_effect=concurrent_create), \
                    patch.object(writer, 'write_frames', return_value=Mock()) as encoder:
                writer.OpenWriter(p, [])
                encoder.assert_called_once()
            self.assertEqual((folder / 'frame_metadata.csv').read_text(), 'preserve me')

    def test_directory_conflicting_file_still_fails(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'cam3'
            path.write_text('preserve me')
            with self.assertRaises(OSError):
                writer.OpenWriter(dict(saveFolder=root, cameraName='cam3',
                                       videoFilename='test.mp4'), [])
            self.assertEqual(path.read_text(), 'preserve me')

    def run_wait(self, action):
        code = (
            'import time; from campy.start_signal import wait_for_start; '
            'deadline=time.monotonic()+0.3; '
            'print(wait_for_start(lambda: time.monotonic()>deadline), flush=True)'
        )
        child = subprocess.Popen([sys.executable, '-B', '-c', code],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        try:
            if action == 'enter':
                child.stdin.write(b'\n')
                child.stdin.flush()
            elif action == 'eof':
                child.stdin.close()
            # Leave the pipe OPEN on cancel: this previously caused fatal shutdown.
            self.assertEqual(child.wait(timeout=10), 0)
            self.assertEqual(child.stdout.read().strip(),
                             b'True' if action == 'enter' else b'False')
            self.assertEqual(child.stderr.read(), b'')
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()

    def test_cancel_with_gui_stdin_still_open(self):
        self.run_wait('cancel')

    def test_gui_enter(self):
        self.run_wait('enter')

    def test_gui_eof(self):
        self.run_wait('eof')
