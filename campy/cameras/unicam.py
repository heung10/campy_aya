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
from campy.recording_runtime import MetadataJournal, RuntimeStatus, LatestWorker, FRAME_HEADER, bounded_call, atomic_json

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
		# RuntimeStatus publishes the same schema outside the acquisition loop.
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


def GrabFrames(cam_params, writeQueue, dispQueue, stopReadQueue, stopWriteQueue, readyQueue=None, triggerStartEvent=None, stopEvent=None, cameraInitialized=None):
	camera = None
	journal = runtime = preview = None
	grabdata = GrabData(cam_params)
	cam_params["framesQueued"] = 0
	cam_params["queueHighWaterMark"] = 0
	try:
		cam, camera, cam_params = OpenCamera(cam_params, stopWriteQueue)
		if cameraInitialized is not None:
			cameraInitialized.set()
		if camera is None:
			raise RuntimeError("Camera could not be opened")
		folder = os.path.join(cam_params["saveFolder"], cam_params["cameraName"])
		journal = MetadataJournal(folder, cam_params.get("metadataFlushIntervalSec", 1.0))
		SaveParameterMetadata(cam_params, grabdata)
		runtime = RuntimeStatus(cam_params)
		if cam_params.get("guiPreviewEnabled", False):
			preview = LatestWorker(lambda img: SaveGuiPreviewFrame(cam_params, img),
				cam_params.get("guiPreviewFrameRate", 20))
		if not StartGrabbing(camera, cam_params, cam):
			raise RuntimeError("Camera failed to start grabbing")
		WaitForTriggerStart(cam_params, readyQueue, triggerStartEvent)
		frameNumber = 0
		stop_drain_started = None
		post_stop_drain_sec = max(1.0, float(cam_params.get("postStopDrainSec", 30.0)))
		while not stopReadQueue:
			if journal.error:
				raise RuntimeError("Incremental metadata failed: {}".format(journal.error))
			stopping = stopEvent is not None and stopEvent.is_set()
			if stopping:
				if stop_drain_started is None:
					stop_drain_started = time.perf_counter()
				elif time.perf_counter()-stop_drain_started >= post_stop_drain_sec:
					logging.warning("%s drain limit reached; camera buffer may remain", cam_params["cameraName"])
					break
			grabResult = None
			try:
				grabResult = cam.GrabFrame(camera, frameNumber, cam_params)
				if hasattr(cam, "GrabSucceeded") and not cam.GrabSucceeded(grabResult):
					grabdata["failedGrabCount"] += 1
					continue
				# Extract a complete row before committing either the image or metadata.
				img = cam.GetImageArray(grabResult)
				timeStamp = cam.GetTimeStamp(grabResult)
				frameID = cam.GetFrameID(grabResult)
				hostDateTime = datetime.now()
				hostTimeStamp = time.perf_counter()
				iso = hostDateTime.isoformat(timespec="microseconds")
				epoch = "{:.6f}".format(hostDateTime.timestamp())
				frameNumber += 1
				if grabdata["frameID"] and frameID != grabdata["frameID"][-1]+1:
					grabdata["frameIdGapCount"] += 1
				for key, value in zip(['frameNumber','frameID','timeStamp','hostTimeStamp','hostDateTimeIso','hostDateTimeEpochSec'],
					[frameNumber,frameID,timeStamp,hostTimeStamp,iso,epoch]):
					grabdata[key].append(value)
				if grabdata["firstHostTime"] is None:
					grabdata["firstHostTime"] = hostTimeStamp
				writeQueue.append(img)
				cam_params["framesQueued"] += 1
				cam_params["queueHighWaterMark"] = max(cam_params["queueHighWaterMark"], len(writeQueue))
				journal.append([frameNumber,frameID,timeStamp-grabdata['timeStamp'][0],
					hostTimeStamp-grabdata['hostTimeStamp'][0],iso,epoch])
				runtime.observe(frameNumber,timeStamp,hostTimeStamp,float(epoch),len(writeQueue))
				if not stopping:
					if preview and frameNumber % grabdata["frameRatio"] == 0:
						# Basler Array is an owned copy. Keep only the latest image reference.
						preview.submit(img)
					if frameNumber % grabdata["frameRatio"] == 0 and cam_params["displayFrameRate"] > 0:
						cam.DisplayImage(cam_params, dispQueue, grabResult)
				CountFPS(cam_params, grabdata, frameNumber, timeStamp)
				if ShouldStopAcquisition(cam_params, grabdata, frameNumber) and not stopping:
					break
			except Exception as exc:
				if cam_params["cameraMake"] == "basler" and "Grab timed out" in str(exc):
					if stopping:
						break  # Retrieval timeout after draining: no further result available.
					grabdata["timeoutCount"] += 1
				elif "Pixel format currently not supported" in str(exc):
					grabdata["failedGrabCount"] += 1
				else:
					grabdata["otherErrorCount"] += 1
					logging.exception("%s frame acquisition failed", cam_params["cameraName"])
				if journal.error:
					raise
				time.sleep(.001)
			finally:
				if grabResult is not None:
					cam.ReleaseFrame(grabResult)
			# All SDK controls stay on the camera owner thread, after releasing buffer.
			if not stopping:
				runtime.apply_pending(cam, camera)
	except BaseException:
		logging.exception("Acquisition ended unexpectedly for %s", cam_params["cameraName"])
		if readyQueue is not None:
			readyQueue.put({'error': 'Camera {} acquisition failed'.format(cam_params['cameraName'])})
		if stopEvent is not None:
			stopEvent.set()
	finally:
		if cameraInitialized is not None:
			cameraInitialized.set()
		# Signal the writer immediately; it still drains its entire image queue.
		stopWriteQueue.append('STOP')
		if preview:
			preview.close()
		if runtime:
			runtime.close()
		if journal:
			try:
				journal.close()
			except Exception:
				logging.exception("Metadata journal close failed; preserving partial CSV")
		# Save before hardware close: a hung device cannot prevent exports.
		SaveMetadata(cam_params, grabdata, write_frame_csv=journal is None or
			(journal.error is not None and not journal.thread.is_alive()))
		if camera is not None:
			def close_camera():
				try:
					if hasattr(cam, 'ReadTransportStatistics'):
						atomic_json(Path(cam_params['saveFolder'])/cam_params['cameraName']/'transport_diagnostics.json',
							cam.ReadTransportStatistics(camera))
				except Exception:
					logging.exception('Transport statistics unavailable')
				finally:
					cam.CloseCamera(cam_params, camera)
			bounded_call("Close camera " + cam_params["cameraName"],
				close_camera, 5.0)
		if cam_params["displayFrameRate"] > 0:
			dispQueue.append('STOP')


def SaveParameterMetadata(cam_params, grabdata):
	folder = Path(cam_params["saveFolder"]) / cam_params["cameraName"]
	folder.mkdir(parents=True, exist_ok=True)
	meta = dict(cam_params)
	times = grabdata['timeStamp']
	host = grabdata['hostTimeStamp']
	meta.update(totalFrames=len(times), totalTime=times[-1]-times[0] if times else 0.0,
		hostTotalTime=host[-1]-host[0] if host else 0.0)
	for key in ['timeoutCount','failedGrabCount','otherErrorCount','frameIdGapCount']:
		meta[key] = grabdata[key]
	for key in ['framesQueued','queueHighWaterMark']:
		meta[key] = cam_params.get(key, 0)
	path = folder/'metadata.csv'
	temp = folder/'metadata.csv.tmp'
	with temp.open('w',newline='') as f:
		w = csv.writer(f,quoting=csv.QUOTE_ALL)
		for key,value in meta.items():
			if isinstance(value,(list,str,int,float)):
				w.writerow([key,value])
	os.replace(str(temp),str(path))


def SaveMetadata(cam_params, grabdata, write_frame_csv=True):
	folder = Path(cam_params["saveFolder"]) / cam_params["cameraName"]
	folder.mkdir(parents=True, exist_ok=True)
	keys = ['frameNumber','frameID','timeStamp','hostTimeStamp','hostDateTimeIso','hostDateTimeEpochSec']
	data = {key:list(grabdata[key]) for key in keys}
	for key in ['timeStamp','hostTimeStamp']:
		if data[key]:
			first = data[key][0]
			data[key] = [value-first for value in data[key]]
	def save_npy():
		with (folder/'frametimes.npy.tmp').open('wb') as f:
			np.save(f,np.array([data[key] for key in keys],dtype=object))
		os.replace(str(folder/'frametimes.npy.tmp'),str(folder/'frametimes.npy'))
	def save_mat():
		if sio is not None:
			sio.savemat(str(folder/'frametimes.mat.tmp'),data,do_compression=True,appendmat=False)
			os.replace(str(folder/'frametimes.mat.tmp'),str(folder/'frametimes.mat'))
		else:
			logging.warning('MAT export unavailable: %s', SCIPY_IO_ERROR)
	def save_csv():
		with (folder/'frame_metadata.csv.tmp').open('w',newline='') as f:
			w=csv.writer(f); w.writerow(FRAME_HEADER)
			w.writerows(zip(*(data[key] for key in keys)))
		os.replace(str(folder/'frame_metadata.csv.tmp'),str(folder/'frame_metadata.csv'))
	operations = [('metadata.csv',lambda: SaveParameterMetadata(cam_params,grabdata)),
		('frametimes.npy',save_npy),('frametimes.mat',save_mat)]
	if write_frame_csv:
		operations.insert(0,('frame_metadata.csv',save_csv))
	for label, operation in operations:
		try:
			operation()
		except Exception:
			logging.exception('Could not save %s for %s',label,cam_params['cameraName'])
	print('Saved metadata for {}.'.format(cam_params['cameraName']),flush=True)


def CloseSystems(systems, params):
	print('Closing systems...')
	makes = GetMakeList(params)
	for m in range(len(makes)):
		cam = ImportCam(makes[m])
		cam.CloseSystem(systems[makes[m]]["system"], systems[makes[m]]["deviceList"])
	print('Exiting campy...')
