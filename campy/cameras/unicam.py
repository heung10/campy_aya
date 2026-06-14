"""
Unicam unifies camera APIs with common syntax to simplify multi-camera acquisition and 
reduce redundancy in campy code.
"""

import os, sys, time, csv, logging
import numpy as np
from collections import deque
from scipy import io as sio


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
	grabdata["frameNumber"] = []
	grabdata["frameID"] = []
	grabdata["cameraName"] = cam_params["cameraName"]
	grabdata["timeoutCount"] = 0
	grabdata["otherErrorCount"] = 0
	grabdata["failedGrabCount"] = 0
	grabdata["frameIdGapCount"] = 0
	grabdata["firstHostTime"] = None

	# Calculate display rate
	if cam_params["displayFrameRate"] <= 0:
		grabdata["frameRatio"] = float('inf')
	elif cam_params["displayFrameRate"] > 0 and cam_params["displayFrameRate"] <= cam_params['frameRate']:
		grabdata["frameRatio"] = int(round(cam_params["frameRate"]/cam_params["displayFrameRate"]))
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


def CountFPS(grabdata, frameNumber, timeStamp):
	if frameNumber % grabdata["chunkLengthInFrames"] == 0:
		timeElapsed = timeStamp - grabdata["timeStamp"][0]
		fpsCount = round((frameNumber - 1) / timeElapsed, 1)
		print('{} collected {} frames at {} fps for {} sec.'\
			.format(grabdata["cameraName"], frameNumber, fpsCount, round(timeElapsed)))


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
	while(not stopReadQueue and not (stopEvent is not None and stopEvent.is_set())):
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
			hostTimeStamp = time.perf_counter()
			grabdata['hostTimeStamp'].append(hostTimeStamp)
			if grabdata["firstHostTime"] is None:
				grabdata["firstHostTime"] = hostTimeStamp
			frameID = cam.GetFrameID(grabResult)
			if grabdata["frameID"] and frameID != grabdata["frameID"][-1] + 1:
				grabdata["frameIdGapCount"] += 1
			grabdata["frameID"].append(frameID)

			# Display converted, downsampled image in the Window
			if cam_params["displayFrameRate"] > 0 and frameNumber % grabdata["frameRatio"] == 0:
				cam.DisplayImage(cam_params, dispQueue, grabResult)

			CountFPS(grabdata, frameNumber, timeStamp)

			cam.ReleaseFrame(grabResult)

			if ShouldStopAcquisition(cam_params, grabdata, frameNumber):
				break

		except Exception as e:
			# External-triggered Basler acquisition can legitimately poll between
			# triggers, so suppress timeout spam and keep waiting for the next frame.
			if cam_params["cameraMake"] == "basler" and "Grab timed out" in str(e):
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
	full_folder_name = os.path.join(cam_params["videoFolder"], cam_params["cameraName"])

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
		], dtype=object)
		np.save(npy_filename,x)

		# Also save frame data to MATLAB file
		mat_filename = os.path.join(full_folder_name, 'frametimes.mat')
		matdata = {};
		matdata['frameNumber'] = grabdata['frameNumber']
		matdata['frameID'] = grabdata['frameID']
		matdata['timeStamp'] = grabdata['timeStamp']
		matdata['hostTimeStamp'] = grabdata['hostTimeStamp']
		sio.savemat(mat_filename, matdata, do_compression=True)

		# Save per-frame metadata in a CSV that is easier to inspect directly.
		frame_meta_filename = os.path.join(full_folder_name, 'frame_metadata.csv')
		with open(frame_meta_filename, 'w', newline='') as f:
			w = csv.writer(f, delimiter=',', quoting=csv.QUOTE_MINIMAL)
			w.writerow(["savedFrameNumber", "cameraFrameID", "cameraTimeStampSec", "hostTimeStampSec"])
			for i in range(len(grabdata['frameNumber'])):
				w.writerow([
					grabdata['frameNumber'][i],
					grabdata['frameID'][i],
					grabdata['timeStamp'][i],
					grabdata['hostTimeStamp'][i],
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
