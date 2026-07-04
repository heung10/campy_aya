"""
"""
import pypylon.pylon as pylon
import pypylon.genicam as geni
from campy.cameras import unicam
import os, sys, time, logging
import numpy as np
from collections import deque


def LoadSystem(params):

	return pylon.TlFactory.GetInstance()


def GetDeviceList(system):
	return EnumerateBaslerDevices(system)


def EnumerateBaslerDevices(system):
	devices = []
	seen = set()

	def device_key(device_info):
		try:
			full_name = device_info.GetFullName()
			if full_name not in [None, "", "N/A"]:
				return ("full", str(full_name))
		except Exception:
			pass

		try:
			serial = device_info.GetSerialNumber()
		except Exception:
			serial = ""
		try:
			device_class = device_info.GetDeviceClass()
		except Exception:
			device_class = ""
		try:
			model = device_info.GetModelName()
		except Exception:
			model = ""
		return ("fallback", str(serial), str(device_class), str(model))

	def add_devices(found_devices, source_label):
		added = 0
		for device_info in found_devices:
			key = device_key(device_info)
			if key in seen:
				continue
			seen.add(key)
			devices.append(device_info)
			added += 1
		print("Basler discovery {}: {} device(s).".format(source_label, added), flush=True)

	try:
		add_devices(system.EnumerateDevices(), "factory EnumerateDevices")
	except Exception as e:
		logging.warning("Basler factory enumeration failed: %s", e)

	try:
		for tl_info in system.EnumerateTls():
			try:
				device_class = tl_info.GetDeviceClass()
			except Exception:
				device_class = "Unknown"

			try:
				tl = system.CreateTl(tl_info)
			except Exception as e:
				logging.warning("Could not create transport layer %s: %s", device_class, e)
				continue

			try:
				add_devices(tl.EnumerateDevices(), "{} EnumerateDevices".format(device_class))
			except Exception as e:
				logging.warning("%s device enumeration failed: %s", device_class, e)

			if device_class == "BaslerGigE" and hasattr(tl, "EnumerateAllDevices"):
				try:
					add_devices(tl.EnumerateAllDevices(), "{} EnumerateAllDevices".format(device_class))
				except Exception as e:
					logging.warning("%s all-device enumeration failed: %s", device_class, e)
	except Exception as e:
		logging.warning("Basler transport-layer enumeration failed: %s", e)

	for index, device_info in enumerate(devices):
		try:
			print(
				"Basler device {}: serial {} model {} class {} tl {}.".format(
					index,
					device_info.GetSerialNumber(),
					device_info.GetModelName(),
					device_info.GetDeviceClass(),
					device_info.GetTLType() if hasattr(device_info, "GetTLType") else "Unknown",
				),
				flush=True,
			)
		except Exception:
			pass

	return devices


def LoadDevice(systems, params, cam_params):
	# system = params["systems"]["basler"]["system"]
	system = systems["basler"]["system"]
	cam_params["camera"] = system.CreateDevice(cam_params["device"])
	return cam_params


def GetSerialNumber(device):

	return device.GetSerialNumber()


def GetModelName(camera):

	return camera.GetDeviceInfo().GetModelName()


def OpenCamera(cam_params):
	# Open the camera
	camera = pylon.InstantCamera(cam_params["camera"])
	camera.Open()

	# Load default camera settings
	cam_params['cameraModel'] = GetModelName(camera)
	cam_params = LoadSettings(cam_params, camera)

	return camera, cam_params


def LoadSettings(cam_params, camera):
	# Load settings from Pylon features file
	pylon.FeaturePersistence.Load(cam_params['cameraSettings'], camera.GetNodeMap(), False) #Validation is false
	camera.MaxNumBuffer = cam_params["bufferSize"] # default bufferSize is ~500 frames

	# Manual override settings
	if cam_params["cameraTrigger"] == "Software" or cam_params["cameraTrigger"] == "software":
		camera.TriggerMode.SetValue('Off')
		camera.AcquisitionFrameRateEnable.SetValue(True)
		camera.AcquisitionFrameRate.SetValue(cam_params["frameRate"])
	
	# Get camera information and save to cam_params for metadata
	cam_params['frameWidth'] = camera.Width.GetValue()
	cam_params['frameHeight'] = camera.Height.GetValue()
	if cam_params.get("overrideCameraExposureTime", False):
		ConfigureExposure(camera, cam_params, silent=True)
	else:
		applied_exposure = ReadExposure(camera)
		if applied_exposure is not None:
			cam_params["appliedExposureTimeInUs"] = applied_exposure
			cam_params["cameraExposureTimeInUs"] = applied_exposure
	print(
		"{} applied exposure time {:.1f} us.".format(
			cam_params["cameraName"],
			float(cam_params.get("appliedExposureTimeInUs", cam_params["cameraExposureTimeInUs"])),
		),
		flush=True,
	)

	ConfigureOutputLine(cam_params, camera)

	return cam_params


def ConfigureOutputLine(cam_params, camera):
	line_source = cam_params.get("cameraOutSource", "None")
	line_out = cam_params.get("cameraOut", "None")
	line_name = NormalizeLineName(line_out)
	if line_source in [None, "None"] or line_name is None:
		return

	try:
		camera.LineSelector.SetValue(line_name)
		camera.LineMode.SetValue("Output")
		camera.LineSource.SetValue(str(line_source))
		print(
			"Configured {} output {} -> {}.".format(
				cam_params["cameraName"],
				line_name,
				line_source,
			),
			flush=True,
		)
	except Exception as e:
		raise RuntimeError(
			"Unable to configure {} output {} to {}: {}".format(
				cam_params["cameraName"],
				line_name,
				line_source,
				e,
			)
		)


def NormalizeLineName(line_value):
	if line_value in [None, "None", "none", 0, "0"]:
		return None
	if isinstance(line_value, str):
		line_value = line_value.strip()
		if line_value.lower().startswith("line"):
			return "Line{}".format(line_value[4:])
		return "Line{}".format(int(line_value))
	return "Line{}".format(int(line_value))


def ConfigureExposure(camera, cam_params, exposure_time_us=None, silent=False):
	exposure_time_us = float(
		cam_params["cameraExposureTimeInUs"] if exposure_time_us is None else exposure_time_us
	)
	ValidateExposureTime(cam_params, exposure_time_us)

	try:
		try:
			camera.ExposureAuto.SetValue("Off")
		except Exception:
			pass

		applied = _set_float_feature(camera, ["ExposureTime", "ExposureTimeAbs"], exposure_time_us)
		if applied is None:
			raise RuntimeError("ExposureTime feature is not writable on this camera.")

		cam_params["cameraExposureTimeInUs"] = applied
		cam_params["appliedExposureTimeInUs"] = applied
		if not silent:
			print(
				"{} exposure time set to {:.1f} us.".format(
					cam_params["cameraName"],
					applied,
				),
				flush=True,
			)
		return cam_params
	except Exception as e:
		raise RuntimeError(
			"Unable to set exposure time for {}: {}".format(
				cam_params["cameraName"],
				e,
			)
		)


def ValidateExposureTime(cam_params, exposure_time_us):
	frame_rate = float(cam_params.get("frameRate", 0) or 0)
	if frame_rate <= 0:
		return

	frame_period_us = 1e6 / frame_rate
	if float(exposure_time_us) >= frame_period_us:
		raise RuntimeError(
			"Requested exposure time {:.1f} us must be shorter than one frame period at {:.3f} Hz ({:.1f} us).".format(
				float(exposure_time_us),
				frame_rate,
				frame_period_us,
			)
		)


def ReadExposure(camera):
	value = _get_float_feature(camera, ["ExposureTime", "ExposureTimeAbs"])
	return float(value) if value is not None else None


def _set_float_feature(camera, feature_names, value):
	for feature_name in feature_names:
		try:
			node = getattr(camera, feature_name)
			minimum = float(node.GetMin())
			maximum = float(node.GetMax())
			applied = max(minimum, min(maximum, float(value)))
			node.SetValue(applied)
			return applied
		except Exception:
			pass

	nodemap = camera.GetNodeMap()
	for feature_name in feature_names:
		try:
			node = geni.CFloatPtr(nodemap.GetNode(feature_name))
			if not geni.IsAvailable(node) or not geni.IsWritable(node):
				continue
			minimum = float(node.GetMin())
			maximum = float(node.GetMax())
			applied = max(minimum, min(maximum, float(value)))
			node.SetValue(applied)
			return applied
		except Exception:
			pass
	return None


def _get_float_feature(camera, feature_names):
	for feature_name in feature_names:
		try:
			node = getattr(camera, feature_name)
			return float(node.GetValue())
		except Exception:
			pass

	nodemap = camera.GetNodeMap()
	for feature_name in feature_names:
		try:
			node = geni.CFloatPtr(nodemap.GetNode(feature_name))
			if not geni.IsAvailable(node):
				continue
			return float(node.GetValue())
		except Exception:
			pass
	return None


def ApplyRuntimeControls(camera, cam_params, control):
	if not isinstance(control, dict):
		return cam_params

	requested = None
	camera_controls = control.get("cameras")
	if isinstance(camera_controls, dict):
		camera_control = camera_controls.get(cam_params["cameraName"])
		if isinstance(camera_control, dict):
			try:
				requested = float(camera_control["cameraExposureTimeInUs"])
			except Exception:
				requested = None

	if requested is None and "cameraExposureTimeInUs" in control:
		try:
			requested = float(control["cameraExposureTimeInUs"])
		except Exception:
			requested = None

	if requested is None:
		return cam_params

	current = float(cam_params.get("appliedExposureTimeInUs", cam_params.get("cameraExposureTimeInUs", requested)))
	if abs(requested - current) < 0.5:
		return cam_params

	return ConfigureExposure(camera, cam_params, exposure_time_us=requested)


def StartGrabbing(camera):
	try:
		camera.StartGrabbing(pylon.GrabStrategy_OneByOne)
		return True
	except Exception:
		return False


def GrabFrame(camera, frameNumber, cam_params):
	timeout_ms = int(cam_params.get("grabTimeoutInMs", 1000))
	return camera.RetrieveResult(timeout_ms, pylon.TimeoutHandling_ThrowException)


def GetImageArray(grabResult):

	return grabResult.Array


def GetTimeStamp(grabResult):

	return grabResult.TimeStamp*1e-9


def GetFrameID(grabResult):

	return int(grabResult.GetBlockID())


def GrabSucceeded(grabResult):

	return grabResult.GrabSucceeded()


def DisplayImage(cam_params, dispQueue, grabResult):
	# Use a generic NumPy-based preview path for external-triggered runs.
	if cam_params["pixelFormatInput"].find("bayer") != -1:
		converter = pylon.ImageFormatConverter()
		converter.OutputPixelFormat = pylon.PixelType_RGB8packed
		img = converter.Convert(grabResult).GetArray()
	else:
		# Use the same extraction path as recording to avoid preview-only
		# "Pixel format currently not supported" errors on some Basler results.
		img = GetImageArray(grabResult)

	# Downsample image
	if img.ndim == 3:
		img = img[::cam_params["displayDownsample"],::cam_params["displayDownsample"],:]
	else:
		img = img[::cam_params["displayDownsample"],::cam_params["displayDownsample"]]

	# Send image to display queue
	dispQueue.append(img)


def ReleaseFrame(grabResult):

	grabResult.Release()


def CloseCamera(cam_params, camera):
	print('Closing {}... Please wait.'.format(cam_params["cameraName"]))
	# Close Basler camera after acquisition stops
	camera.StopGrabbing()
	camera.Close()


def CloseSystem(system, device_list):
	del system
	del device_list


# Basler-Specific Functions
def OpenPylonImageWindow(cam_params):
	return None
