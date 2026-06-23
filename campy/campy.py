"""
CamPy: Python-based multi-camera recording software.
Integrates machine vision camera APIs with ffmpeg real-time compression.
Outputs one MP4 video file and metadata files for each camera

"campy" is the main console. 
User inputs are loaded from config yaml file using a command line interface (CLI) 
configurator parses the config arguments (and default params) into "params" dictionary.
configurator assigns params to each camera stream in the "cam_params" dictionary.
	* Camera index is set by "cameraSelection".
	* If param is string, it is applied to all cameras.
	* If param is list of strings, it is assigned to each camera, ordered by camera index.
Camera streams are acquired and encoded in parallel using multiprocessing.

Usage: 
campy-acquire ./configs/campy_config.yaml
"""

import os, time, sys, logging, threading, queue
from collections import deque
import multiprocessing as mp
from campy import writer, display, configurator
from campy.gpio import logger as gpio_logger
from campy.trigger import trigger
from campy.cameras import unicam

def OpenSystems():
	# Configure parameters
	params = configurator.ConfigureParams()

	# Load Camera Systems and Devices
	systems = unicam.LoadSystems(params)
	systems = unicam.GetDeviceList(systems, params)

	return systems, params


def CloseSystems(systems, params):
	trigger.StopTriggerOutputs(systems, params)
	unicam.CloseSystems(systems, params)
	gpio_logger.StopLogging(systems)
	trigger.CloseTriggerController(systems, params)


def TriggerPeriodSec(params):
	if params["triggerController"] in ["PulsePal", "pulsepal"]:
		return 1.0 / float(params["pulseFrequencyHz"])
	return 1.0 / float(params["frameRate"])


def StartSynchronizedTrigger(systems, params, triggerStartEvent=None):
	# Release camera workers first so they are actively waiting on hardware
	# triggers before Pulse Pal starts generating pulses.
	if triggerStartEvent is not None:
		triggerStartEvent.set()
		time.sleep(min(0.1, max(TriggerPeriodSec(params), 0.02)))

	if TriggerControllerEnabled(params):
		trigger.StartTriggers(systems, params)


def StopSynchronizedTrigger(systems, params, stopEvent=None, triggerStartEvent=None):
	# If cameras are still waiting for the first trigger, release them so the
	# worker processes can unwind cleanly.
	if triggerStartEvent is not None:
		triggerStartEvent.set()

	# Stop outgoing pulses first so GPIO and camera frame counts stop advancing.
	trigger.StopTriggerOutputs(systems, params)

	# Allow at most one in-flight trigger period to drain before stopping the
	# camera processes.
	if stopEvent is not None:
		time.sleep(min(0.1, max(TriggerPeriodSec(params), 0.02)))
		stopEvent.set()


def AcquireOneCamera(args):
	if isinstance(args, tuple):
		n_cam, readyQueue, triggerStartEvent, stopEvent = args
	else:
		n_cam = args
		readyQueue = None
		triggerStartEvent = None
		stopEvent = None

	# Initialize param dictionary for this camera stream
	cam_params = configurator.ConfigureCamParams(systems, params, n_cam)

	# Initialize queues for display, video writer, and stop messages
	dispQueue = deque([], 2)
	writeQueue = deque()
	stopReadQueue = deque([],1)
	stopWriteQueue = deque([],1)

	# Start image window display thread
	if cam_params["displayFrameRate"] > 0:
		threading.Thread(
			target = display.DisplayFrames,
			daemon = True,
			args = (cam_params, dispQueue,),
			).start()

	# Start grabbing frames ("producer" thread)
	threading.Thread(
		target = unicam.GrabFrames,
		daemon = True,
		args = (cam_params, writeQueue, dispQueue, stopReadQueue, stopWriteQueue, readyQueue, triggerStartEvent, stopEvent,),
		).start()

	# Start video file writer (main "consumer" process)
	writer.WriteFrames(cam_params, writeQueue, stopReadQueue, stopWriteQueue)


def TriggerControllerEnabled(params):
	return params["startArduino"] or params["startTriggerController"]


def WaitForCamerasReady(readyQueue, acquireResult):
	ready_cameras = set()
	while len(ready_cameras) < params["numCams"]:
		if acquireResult.ready():
			acquireResult.get()
		try:
			camera_name = readyQueue.get(timeout=0.25)
			ready_cameras.add(camera_name)
			print("{}/{} cameras ready: {}".format(
				len(ready_cameras),
				params["numCams"],
				", ".join(sorted(ready_cameras)),
			), flush=True)
		except queue.Empty:
			continue


def Main():
	triggerStartEvent = None
	stopEvent = None
	p = None

	try:
		try:
			# Acquire cameras in parallel with Windows- and Linux-compatible pool
			mp_context = mp.get_context("spawn")
			manager = mp_context.Manager()
			stopEvent = manager.Event()
			p = mp_context.Pool(params["numCams"])

			if TriggerControllerEnabled(params) and not params["waitForTriggerStart"]:
				gpio_logger.StartLogging(systems, params)
				StartSynchronizedTrigger(systems, params)

			if params["waitForTriggerStart"]:
				readyQueue = manager.Queue()
				triggerStartEvent = manager.Event()
				cameraArgs = [(n_cam, readyQueue, triggerStartEvent, stopEvent) for n_cam in range(params["numCams"])]
			else:
				cameraArgs = [(n_cam, None, None, stopEvent) for n_cam in range(params["numCams"])]

			acquireResult = p.map_async(AcquireOneCamera, cameraArgs)

			if params["waitForTriggerStart"]:
				WaitForCamerasReady(readyQueue, acquireResult)
				print("All cameras are ready. Press Enter to start {} trigger.".format(
					params["triggerController"]
				), flush=True)
				input()
				gpio_logger.StartLogging(systems, params)
				StartSynchronizedTrigger(systems, params, triggerStartEvent)

			acquireResult.get()
		except KeyboardInterrupt:
			print("Stopping acquisition...", flush=True)
			StopSynchronizedTrigger(systems, params, stopEvent, triggerStartEvent)
		finally:
			if p is not None:
				p.close()
				p.join()
	finally:
		CloseSystems(systems, params)

# Open systems, creates global 'systems' and 'params' variables
systems, params = OpenSystems()
