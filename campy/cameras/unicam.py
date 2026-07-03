"""
Unicam unifies camera APIs with common syntax to simplify multi-camera acquisition and 
reduce redundancy in campy code.
"""

import os, sys, time, csv, logging
from pathlib import Path
from datetime import datetime
import numpy as np
from collections import deque
import imageio.v2 as imageio

try:
	from scipy import io as sio
	SCIPY_IO_ERROR = None
except Exception as e:
	sio = None
	SCIPY_IO_ERROR = e


def ImportCam(make):
	if make == "basler":
		from campy.cameras import basler as cam
	elif make == "flir":
		from campy.cameras import flir as cam
	elif make == "emu":
		from campy.cameras import emu as cam
	else:
		print('Camera make is not supported by CamPy. Check config.', flush=True)
	return cam


def LoadSystems(params):
	try:
		systems = {}
		makes = GetMakeList(params)
		for m in range(len(makes)):
			systems[makes[m]] = {}
			cam = ImportCam(makes[m])
			systems[makes[m]]["system"] = cam.LoadSystem(params)
	except Exception as e:
		logging.error('Caught exception at camera/unicam.py LoadSystems. Check cameraMake: {}'.format(e))
		raise
	return systems


def LoadDevice(systems, params, cam_params):
	try:
		cam = ImportCam(cam_params["cameraMake"])
		cam_params = cam.LoadDevice(systems, params, cam_params)
	except Exception as e:
		logging.error('Caught exception at camera/unicam.py LoadSystems. Check cameraMake: {}'.format(e))
		raise
	return cam_params


def OpenCamera(cam_params, stopWriteQueue):
	# Import the cam module
	cam = ImportCam(cam_params["cameraMake"])
	camera = None

	try:
		camera, cam_params = cam.OpenCamera(cam_params)

		print("Opened {}: {} {} serial# {}".format( \
			cam_params["cameraName"],
			cam_params["cameraMake"], 
			cam_params["cameraModel"],
			cam_params["cameraSerialNo"]))

	except Exception as e:
		logging.error("Caught error at cameras/unicam.py OpenCamera: {}".format(e))
		stopWriteQueue.append('STOP')

	return cam, camera, cam_params


def GetDeviceList(systems, params):
	makes = GetMakeList(params)
	for m in range(len(makes)):
		cam = ImportCam(makes[m])
		system = systems[makes[m]]["system"]
		deviceList = cam.GetDeviceList(system)
		serials = [cam.GetSerialNumber(deviceList[i]) for i in range(len(deviceList))]
		systems[makes[m]]["serials"] = serials
		systems[makes[m]]["deviceList"] = deviceList
	return systems


def GetMakeList(params):
	if type(params["cameraMake"]) is list:
		cameraMakes = [params["cameraMake"][m] for m in range(len(params["cameraMake"]))]
	elif type(params["cameraMake"]) is str:
		cameraMakes = [params["cameraMake"]]
	makes = list(set(cameraMakes))
	return makes


def GrabData(cam_params):
	grabdata = {}
	grabdata["timeStamp"] = []
	grabdata["hostTimeStamp"] = []
	grabdata["hostDateTimeIso"] = []
	grabdata["hostDateTimeEpochSec"] = []
	grabdata["frameNumber"] = []
	grabdata["frameID"] = []
	grabdata["cameraName"] = cam_params["cameraName"]
	grabdata["timeoutCount"] = 0
	grabdata["otherErrorCount"] = 0
	grabdata["failedGrabCount"] = 0
	grabdata["frameIdGapCount"] = 0
	grabdata["firstHostTime"] = None

	# Calculate preview/display rate. The Qt GUI uses file-based previews while
	# legacy displayFrameRate controls matplotlib windows.
	preview_rate = 0
	if cam_params.get("guiPreviewEnabled", False):
		preview_rate = cam_params.get("guiPreviewFrameRate", 0)
	display_rate = max(cam_params["displayFrameRate"], preview_rate)
	if display_rate <= 0:
		grabdata["frameRatio"] = float('inf')
	elif display_rate > 0 and display_rate <= cam_params['frameRate']:
		grabdata["frameRatio"] = int(round(cam_params["frameRate"]/display_rate))
	else:
		grabdata["frameRatio"] = cam_params["frameRate"]

	# Calculate number of images and chunk length
	grabdata["numImagesToGrab"] = int(round(cam_params["recTimeInSec"]*cam_params["frameRate"]))
	grabdata["chunkLengthInFrames"] = int(round(cam_params["chunkLengthInSec"]*cam_params["frameRate"]))

	return grabdata


def ShouldStopAcquisition(cam_params, grabdata, frameNumber):
	if cam_params["infiniteRecording"]:
		return False

	# For externally triggered runs, stop by elapsed host time from the first
	# received frame instead of chasing an equal saved-frame count on every
	# camera. This makes cross-camera wall-clock duration comparable even if
	# some frames are lost later in the pipeline.
	if cam_params["cameraTrigger"] not in ["Software", "software"]:
		first_host_time = grabdata["firstHostTime"]
		if first_host_time is None or not grabdata["hostTimeStamp"]:
			return False
		return (grabdata["hostTimeStamp"][-1] - first_host_time) >= cam_params["recTimeInSec"]

	return frameNumber >= grabdata["numImagesToGrab"]


def StartGrabbing(camera, cam_params, cam):
	grabbing = cam.StartGrabbing(camera)
	if grabbing:
		print(cam_params["cameraName"], "ready to trigger.")
	return grabbing


def WaitForTriggerStart(cam_params, readyQueue, triggerStartEvent):
	if readyQueue is not None:
		readyQueue.put(cam_params["cameraName"])
	if triggerStartEvent is not None:
		print(cam_params["cameraName"], "waiting for trigger start.", flush=True)
		triggerStartEvent.wait()


def CountFPS(cam_params, grabdata, frameNumber, timeStamp):
	if frameNumber % grabdata["chunkLengthInFrames"] == 0:
		timeElapsed = timeStamp - grabdata["timeStamp"][0]
		fpsCount = round((frameNumber - 1) / timeElapsed, 1)
		SaveLiveStatus(cam_params, frameNumber, fpsCount, round(timeElapsed))
		print('{} collected {} frames at {} fps for {} sec.'\
			.format(grabdata["cameraName"], frameNumber, fpsCount, round(timeElapsed)), flush=True)


def SaveLiveStatus(cam_params, frameNumber, fpsCount, elapsedSec):
	full_folder_name = os.path.join(cam_params["saveFolder"], cam_params["cameraName"])
	try:
		if not os.path.isdir(full_folder_name):
			os.makedirs(full_folder_name)
		filename = os.path.join(full_folder_name, "live_status.csv")
		tmp_filename = "{}.{}.tmp".format(filename, os.getpid())
		with open(tmp_filename, "w", newline="") as f:
			w = csv.writer(f, delimiter=",", quoting=csv.QUOTE_MINIMAL)
			w.writerow(["cameraName", "framesCollected", "fps", "elapsedSec", "updatedEpochSec"])
			w.writerow([cam_params["cameraName"], frameNumber, fpsCount, elapsedSec, time.time()])
		os.replace(tmp_filename, filename)
	except Exception as e:
		if cam_params.get("cameraDebug", False):
			logging.error('Caught exception at cameras/unicam.py SaveLiveStatus: {}'.format(e))


def SaveGuiPreviewFrame(cam_params, img):
	if not cam_params.get("guiPreviewEnabled", False):
		return
	preview_folder = cam_params.get("guiPreviewFolder", "None")
	if preview_folder in [None, "None", ""]:
		return

	try:
		if not os.path.isdir(preview_folder):
			os.makedirs(preview_folder)

		downsample = max(1, int(cam_params.get("displayDownsample", 1)))
		preview = img[::downsample, ::downsample]

		# Keep previews lightweight and broadly displayable.
		if preview.dtype != np.uint8:
			preview = np.clip(preview, 0, 255).astype(np.uint8)

		filename = os.path.join(preview_folder, "{}.png".format(cam_params["cameraName"]))
		tmp_filename = "{}.{}.{}.tmp.png".format(filename, os.getpid(), time.time_ns())
		imageio.imwrite(tmp_filename, preview)

		# On Windows, Qt/antivirus/filesystem indexing can briefly hold the
		# previous image. Retry the atomic swap instead of logging noisy errors.
		replaced = False
		for _ in range(5):
			try:
				os.replace(tmp_filename, filename)
				replaced = True
				break
			except PermissionError:
				time.sleep(0.01)
		if not replaced:
			try:
				os.remove(tmp_filename)
			except Exception:
				pass
	except Exception as e:
		if cam_params.get("cameraDebug", False):
			logging.error('Caught exception at cameras/unicam.py SaveGuiPreviewFrame: {}'.format(e))


def LoadRuntimeCameraControl(cam_params):
	control_path = cam_params.get("guiCameraControlFile", "None")
	if control_path in [None, "None", ""]:
		return None

	try:
		path = Path(control_path)
		if not path.exists():
			return None
		mtime = path.stat().st_mtime
		if mtime <= float(cam_params.get("_runtimeControlMTime", 0)):
			return None
		with path.open("r", encoding="utf-8") as handle:
			content = handle.read().strip()
		cam_params["_runtimeControlMTime"] = mtime
		if not content:
			return None
		if sio is not None:
			pass
	except Exception as e:
		if cam_params.get("cameraDebug", False):
			logging.error('Caught exception at cameras/unicam.py LoadRuntimeCameraControl: {}'.format(e))
		return None

	try:
		import yaml
		data = yaml.safe_load(content) or {}
		return data if isinstance(data, dict) else None
	except Exception as e:
		if cam_params.get("cameraDebug", False):
			logging.error('Caught exception at cameras/unicam.py ParseRuntimeCameraControl: {}'.format(e))
		return None


def ApplyRuntimeCameraControl(cam, camera, cam_params, frameNumber):
	if frameNumber <= 0 or frameNumber % 5 != 0:
		return cam_params

	control = LoadRuntimeCameraControl(cam_params)
	if control is None:
		return cam_params

	try:
		if hasattr(cam, "ApplyRuntimeControls"):
			return cam.ApplyRuntimeControls(camera, cam_params, control)
	except Exception as e:
		if cam_params.get("cameraDebug", False):
			logging.error('Caught exception at cameras/unicam.py ApplyRuntimeCameraControl: {}'.format(e))
	return cam_params


def GrabFrames(cam_params, writeQueue, dispQueue, stopReadQueue, stopWriteQueue, readyQueue=None, triggerStartEvent=None, stopEvent=None):
	# Open the camera object
	cam, camera, cam_params = OpenCamera(cam_params, stopWriteQueue)

	# Create dictionary for appending frame number and timestamp information
	grabdata = GrabData(cam_params)
	cam_params["framesQueued"] = 0
	cam_params["queueHighWaterMark"] = 0

	# Start grabbing frames from the camera
	grabbing = StartGrabbing(camera, cam_params, cam)
	if not grabbing or camera is None:
		return
	WaitForTriggerStart(cam_params, readyQueue, triggerStartEvent)

	frameNumber = 0
	stop_drain_started = None
	post_stop_drain_sec = float(cam_params.get("postStopDrainSec", 2.0))
	while(not stopReadQueue):
		if stopEvent is not None and stopEvent.is_set():
			if stop_drain_started is None:
				stop_drain_started = time.perf_counter()
			elif time.perf_counter() - stop_drain_started >= post_stop_drain_sec:
				print(
					"{} stop drain reached {} sec; closing camera.".format(
						cam_params["cameraName"],
						post_stop_drain_sec,
					),
					flush=True,
				)
				break
		try:
			# Grab image from camera buffer if available
			grabResult = cam.GrabFrame(camera, frameNumber, cam_params)

			if hasattr(cam, "GrabSucceeded") and not cam.GrabSucceeded(grabResult):
				grabdata["failedGrabCount"] += 1
				cam.ReleaseFrame(grabResult)
				time.sleep(0.001)
				continue

			# Append numpy array to writeQueue for writer to append to file
			img = cam.GetImageArray(grabResult)
			writeQueue.append(img)
			cam_params["framesQueued"] += 1
			cam_params["queueHighWaterMark"] = max(cam_params["queueHighWaterMark"], len(writeQueue))

			# Append timeStamp and frameNumber to grabdata
			frameNumber += 1
			grabdata['frameNumber'].append(frameNumber) # first frame = 1
			timeStamp = cam.GetTimeStamp(grabResult)
			grabdata['timeStamp'].append(timeStamp)
			hostDateTime = datetime.now()
			hostTimeStamp = time.perf_counter()
			grabdata['hostTimeStamp'].append(hostTimeStamp)
			grabdata['hostDateTimeIso'].append(hostDateTime.isoformat(timespec="microseconds"))
			grabdata['hostDateTimeEpochSec'].append("{:.6f}".format(hostDateTime.timestamp()))
			if grabdata["firstHostTime"] is None:
				grabdata["firstHostTime"] = hostTimeStamp
			frameID = cam.GetFrameID(grabResult)
			if grabdata["frameID"] and frameID != grabdata["frameID"][-1] + 1:
				grabdata["frameIdGapCount"] += 1
			grabdata["frameID"].append(frameID)
			cam_params = ApplyRuntimeCameraControl(cam, camera, cam_params, frameNumber)

			# Display/save converted, downsampled previews without touching the
			# recording queue. GUI preview files are latest-frame-only.
			if frameNumber % grabdata["frameRatio"] == 0:
				if cam_params["displayFrameRate"] > 0:
					cam.DisplayImage(cam_params, dispQueue, grabResult)
				SaveGuiPreviewFrame(cam_params, img)

			CountFPS(cam_params, grabdata, frameNumber, timeStamp)

			cam.ReleaseFrame(grabResult)

			if ShouldStopAcquisition(cam_params, grabdata, frameNumber):
				break

		except Exception as e:
			# External-triggered Basler acquisition can legitimately poll between
			# triggers, so suppress timeout spam and keep waiting for the next frame.
			if cam_params["cameraMake"] == "basler" and "Grab timed out" in str(e):
				if stopEvent is not None and stopEvent.is_set():
					break
				grabdata["timeoutCount"] += 1
				time.sleep(0.001)
				continue
			if cam_params["cameraMake"] == "basler" and "Pixel format currently not supported" in str(e):
				grabdata["failedGrabCount"] += 1
				time.sleep(0.001)
				continue
			grabdata["otherErrorCount"] += 1
			if cam_params["cameraDebug"]:
				logging.error('Caught exception at cameras/unicam.py GrabFrames: {}'.format(e))
			time.sleep(0.001)

	# Close the camaera, save metadata, and tell writer and display to close
	cam.CloseCamera(cam_params, camera)
	SaveMetadata(cam_params, grabdata)
	if cam_params["displayFrameRate"] > 0:
		dispQueue.append('STOP')
	stopWriteQueue.append('STOP')


def SaveMetadata(cam_params, grabdata):
	full_folder_name = os.path.join(cam_params["saveFolder"], cam_params["cameraName"])

	try:
		# Zero timeStamps
		timeFirstGrab = grabdata["timeStamp"][0]
		grabdata["timeStamp"] = [i - timeFirstGrab for i in grabdata["timeStamp"]]
		hostFirstGrab = grabdata["hostTimeStamp"][0]
		grabdata["hostTimeStamp"] = [i - hostFirstGrab for i in grabdata["hostTimeStamp"]]

		# Get the frame and time counts to save into metadata
		frame_count = grabdata['frameNumber'][-1]
		time_count = grabdata['timeStamp'][-1]
		fps_count = int(round(frame_count/time_count))
		print('{} saved {} frames at {} fps.'.format(cam_params["cameraName"], frame_count, fps_count))

		meta = cam_params

		# Save frame data to numpy file
		npy_filename = os.path.join(full_folder_name, 'frametimes.npy')
		x = np.array([
			grabdata['frameNumber'],
			grabdata['frameID'],
			grabdata['timeStamp'],
			grabdata['hostTimeStamp'],
			grabdata['hostDateTimeIso'],
			grabdata['hostDateTimeEpochSec'],
		], dtype=object)
		np.save(npy_filename,x)

		# Also save frame data to MATLAB file
		if sio is not None:
			mat_filename = os.path.join(full_folder_name, 'frametimes.mat')
			matdata = {};
			matdata['frameNumber'] = grabdata['frameNumber']
			matdata['frameID'] = grabdata['frameID']
			matdata['timeStamp'] = grabdata['timeStamp']
			matdata['hostTimeStamp'] = grabdata['hostTimeStamp']
			matdata['hostDateTimeIso'] = grabdata['hostDateTimeIso']
			matdata['hostDateTimeEpochSec'] = grabdata['hostDateTimeEpochSec']
			sio.savemat(mat_filename, matdata, do_compression=True)
		else:
			logging.warning(
				"Skipping frametimes.mat export for %s because scipy.io is unavailable: %s",
				cam_params['cameraName'],
				SCIPY_IO_ERROR,
			)

		# Save per-frame metadata in a CSV that is easier to inspect directly.
		frame_meta_filename = os.path.join(full_folder_name, 'frame_metadata.csv')
		with open(frame_meta_filename, 'w', newline='') as f:
			w = csv.writer(f, delimiter=',', quoting=csv.QUOTE_MINIMAL)
			w.writerow([
				"savedFrameNumber",
				"cameraFrameID",
				"cameraTimeStampSec",
				"hostTimeStampSec",
				"hostDateTimeIso",
				"hostDateTimeEpochSec",
			])
			for i in range(len(grabdata['frameNumber'])):
				w.writerow([
					grabdata['frameNumber'][i],
					grabdata['frameID'][i],
					grabdata['timeStamp'][i],
					grabdata['hostTimeStamp'][i],
					grabdata['hostDateTimeIso'][i],
					grabdata['hostDateTimeEpochSec'][i],
				])

		# Save parameters and recording metadata to csv spreadsheet
		csv_filename = os.path.join(full_folder_name, 'metadata.csv')
		meta['totalFrames'] = grabdata['frameNumber'][-1]
		meta['totalTime'] = grabdata['timeStamp'][-1]
		meta['hostTotalTime'] = grabdata['hostTimeStamp'][-1]
		meta['timeoutCount'] = grabdata['timeoutCount']
		meta['failedGrabCount'] = grabdata['failedGrabCount']
		meta['otherErrorCount'] = grabdata['otherErrorCount']
		meta['frameIdGapCount'] = grabdata['frameIdGapCount']
		meta['framesQueued'] = cam_params.get("framesQueued", 0)
		meta['queueHighWaterMark'] = cam_params.get("queueHighWaterMark", 0)
		
		with open(csv_filename, 'w', newline='') as f:
			w = csv.writer(f, delimiter=',', quoting=csv.QUOTE_ALL)
			for row in meta.items():
				# Print items that are not objects or dicts
				if isinstance(row[1],(list,str,int,float)):
					w.writerow(row)

		print('Saved metadata for {}.'.format(cam_params['cameraName']))

	except Exception as e:
		logging.error('Caught exception: {}'.format(e))


def CloseSystems(systems, params):
	print('Closing systems...')
	makes = GetMakeList(params)
	for m in range(len(makes)):
		cam = ImportCam(makes[m])
		cam.CloseSystem(systems[makes[m]]["system"], systems[makes[m]]["deviceList"])
	print('Exiting campy...')
