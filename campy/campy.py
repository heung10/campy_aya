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
	trigger.StopTriggers(systems, params)
	gpio_logger.StopLogging(systems)
	unicam.CloseSystems(systems, params)


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
			gpio_logger.StartLogging(systems, params)

			if TriggerControllerEnabled(params) and not params["waitForTriggerStart"]:
				trigger.StartTriggers(systems, params)

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
				if TriggerControllerEnabled(params):
					trigger.StartTriggers(systems, params)
				triggerStartEvent.set()

			acquireResult.get()
		except KeyboardInterrupt:
			print("Stopping acquisition...", flush=True)
			if stopEvent is not None:
				stopEvent.set()
			if triggerStartEvent is not None:
				triggerStartEvent.set()
			trigger.StopTriggers(systems, params)
		finally:
			if p is not None:
				p.close()
				p.join()
	finally:
		CloseSystems(systems, params)

# Open systems, creates global 'systems' and 'params' variables
systems, params = OpenSystems()
