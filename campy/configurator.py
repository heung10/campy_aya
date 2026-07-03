"""
"""

import os, sys, ast, yaml, time, logging, shutil
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from campy.cameras import unicam


def DefaultParams():
	"""
	Default parameters for campy config.
	Omitted parameters will revert to these default values.
	""" 

	params = {}
	# Recording default parameters
	params["numCams"] = 1
	params["saveFolder"] = "./test"
	params["videoFolder"] = "./test"
	params["videoFilename"] = "0.mp4"
	params["frameRate"] = 100
	params["recTimeInSec"] = 10
	params["infiniteRecording"] = False

	# Camera default parameters
	params["cameraMake"] = "basler"
	params["cameraSettings"] = "None"
	params["cameraSerialNo"] = "None"
	params["frameWidth"] = 1152
	params["frameHeight"] = 1024
	params["cameraDebug"] = False
	params["grabTimeoutInMs"] = 1000

	# Flir camera default parameters
	params["cameraTrigger"] = "None" # "Line3"
	params["cameraOut"] = "Line2"
	params["cameraOutSource"] = "None"
	params["bufferMode"] = "OldestFirst"
	params["bufferSize"] = 100
	params["cameraExposureTimeInUs"] = 1500
	params["cameraGain"] = 1
	params["disableGamma"] = True

	# Compression default parameters
	params["ffmpegLogLevel"] = "quiet"
	params["ffmpegPath"] = "None" # "/home/usr/Documents/ffmpeg/ffmpeg"
	params["pixelFormatInput"] = "rgb24" # "bayer_bggr8" "rgb24"
	params["pixelFormatOutput"] = "rgb0"
	params["gpuID"] = -1
	params["gpuMake"] = "nvidia"
	params["codec"] = "h264"  
	params["quality"] = 21
	params["preset"] = "None"

	# Display parameters
	params["chunkLengthInSec"] = 5
	params["displayFrameRate"] = 10
	params["displayDownsample"] = 2
	params["guiPreviewEnabled"] = False
	params["guiPreviewFrameRate"] = 5
	params["guiPreviewFolder"] = "None"
	params["guiStopFile"] = "None"
	params["guiCameraControlFile"] = "None"

	# Trigger parameters
	params["triggerController"] = "arduino"
	params["startArduino"] = False
	params["startTriggerController"] = False
	params["waitForTriggerStart"] = False
	params["serialPort"] = "COM3"
	params["digitalPins"] = [0,1,2,3,4,5,6]
	params["pulsePalPythonPath"] = "None"
	params["pulsePalPort"] = "COM10"
	params["pulsePalChannels"] = [1,2,3,4]
	params["pulseFrequencyHz"] = 40
	params["pulseHighTimeSec"] = 0.005
	params["pulseTrainDurationSec"] = 1800
	params["pulsePalContinuous"] = True
	params["pulsePalVoltage"] = 5
	params["pulsePalRestingVoltage"] = 0
	params["pulsePalTriggerChannel"] = 1
	params["enableGPIOTimestampLogging"] = False
	params["gpioSerialPort"] = "COM11"
	params["gpioBaudRate"] = 119200
	params["gpioLogFilename"] = "gpio_log.csv"

	return params


def AutoParams(params, default_params):
	# Handle out of range values (reset to default)
	range_params = [
		"numCams",
		"frameRate",
		"recTimeInSec",
		"frameHeight",
		"frameWidth",
		"bufferSize",
		"cameraGain",
		"cameraExposureTimeInUs",
		"quality",
		"chunkLengthInSec",
		"displayDownsample",
		"pulseFrequencyHz",
		"pulseHighTimeSec",
		"pulseTrainDurationSec",
		"pulsePalVoltage",
		]

	for i in range(len(range_params)):
		key = range_params[i]
		default_value = default_params[key]
		value = params[key]
		if type(value) is list:
			invalid = [v <= 0 for v in value]
			if any(invalid):
				replacement = [default_value if invalid[j] else value[j] for j in range(len(value))]
				params[key] = replacement
				print("{} set to invalid value in config. Setting invalid entries to default ({})."\
						.format(key, default_value))
		elif value <= 0:
			params[key] = default_value
			print("{} set to invalid value in config. Setting to default ({})."\
					.format(key, default_value))

	# Allow displayFrameRate == 0 to disable preview, but still reject negatives.
	if type(params["displayFrameRate"]) is list:
		default_value = default_params["displayFrameRate"]
		invalid = [v < 0 for v in params["displayFrameRate"]]
		if any(invalid):
			params["displayFrameRate"] = [default_value if invalid[j] else params["displayFrameRate"][j] for j in range(len(params["displayFrameRate"]))]
			print("{} set to invalid value in config. Setting invalid entries to default ({})."\
					.format("displayFrameRate", default_value))
	elif params["displayFrameRate"] < 0:
		default_value = default_params["displayFrameRate"]
		params["displayFrameRate"] = default_value
		print("{} set to invalid value in config. Setting to default ({})."\
				.format("displayFrameRate", default_value))

	if params["guiPreviewFrameRate"] < 0:
		default_value = default_params["guiPreviewFrameRate"]
		params["guiPreviewFrameRate"] = default_value
		print("{} set to invalid value in config. Setting to default ({})."\
				.format("guiPreviewFrameRate", default_value))

	# Handle missing config parameters
	if "numCams" in params.keys():
		if "cameraNames" not in params.keys():
			params["cameraNames"] = ["Camera%s" % n for n in range(params["numCams"])]
		if "cameraSelection" not in params.keys():
			params["cameraSelection"] = [n for n in range(params["numCams"])]
	else:
		print("Please configure 'numCams' to the number of cameras you want to acquire.")

	return params


def ConfigureParams():
	parser = ArgumentParser(description="Campy CLI", 
						formatter_class=ArgumentDefaultsHelpFormatter,)
	clargs = ParseClargs(parser)
	params = CombineConfigAndClargs(clargs)

	params = ConfigureFFmpeg(params)

	return params


def IsUnset(value):
	return value in [None, "", "None", "none", "auto", "Auto", "AUTO"]


def ConfigureFFmpeg(params):
	ffmpeg_path = params.get("ffmpegPath", "None")
	if IsUnset(ffmpeg_path):
		ffmpeg_path = FindFFmpeg()
	else:
		ffmpeg_path = os.path.expandvars(os.path.expanduser(str(ffmpeg_path)))
		if os.path.isdir(ffmpeg_path):
			ffmpeg_path = os.path.join(
				ffmpeg_path,
				"ffmpeg.exe" if os.name == "nt" else "ffmpeg",
			)
		if not os.path.isfile(ffmpeg_path):
			raise FileNotFoundError(
				"ffmpegPath does not point to an ffmpeg executable: {}".format(ffmpeg_path)
			)

	params["ffmpegPath"] = ffmpeg_path
	os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path
	return params


def FindFFmpeg():
	ffmpeg_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
	candidates = []
	env_prefixes = []
	conda_prefix = os.environ.get("CONDA_PREFIX")
	if conda_prefix:
		env_prefixes.append(conda_prefix)
	if sys.prefix:
		env_prefixes.append(sys.prefix)
	if sys.executable:
		env_prefixes.append(os.path.dirname(os.path.dirname(sys.executable)))

	seen_prefixes = set()
	for prefix in env_prefixes:
		if not prefix:
			continue
		prefix = os.path.abspath(prefix)
		if prefix in seen_prefixes:
			continue
		seen_prefixes.add(prefix)
		candidates.extend([
			os.path.join(prefix, "Library", "bin", ffmpeg_name),
			os.path.join(prefix, "bin", ffmpeg_name),
		])

	path_ffmpeg = shutil.which("ffmpeg")
	if path_ffmpeg:
		candidates.append(path_ffmpeg)

	for candidate in candidates:
		if candidate and os.path.isfile(candidate):
			return candidate

	try:
		import imageio_ffmpeg
		ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
		if ffmpeg_path and os.path.isfile(ffmpeg_path):
			return ffmpeg_path
	except Exception:
		pass

	raise FileNotFoundError(
		"Could not find ffmpeg. Install it in the conda environment or set ffmpegPath."
	)


def NormalizeFolderParams(params):
	# Prefer the clearer saveFolder name, while preserving videoFolder as a
	# backward-compatible alias for older configs and internal call sites.
	save_folder = params.get("saveFolder")
	video_folder = params.get("videoFolder")

	if save_folder not in [None, "None"]:
		params["videoFolder"] = save_folder
	elif video_folder not in [None, "None"]:
		params["saveFolder"] = video_folder
	else:
		params["saveFolder"] = "./test"
		params["videoFolder"] = "./test"

	return params


def ConfigureCamParams(systems, params, n_cam):
	# Insert camera-specific metadata from parameters into cam_params dictionary
	cam_params = params
	cam_params["n_cam"] = n_cam
	cam_params["baseFolder"] = os.getcwd()
	cam_params["cameraName"] = params["cameraNames"][n_cam]

	cam_params = OptParams(cam_params)
	cam_make = cam_params["cameraMake"]
	cam_idx = GetCameraIndex(systems, cam_params)
	cam_params["cameraSelection"] = cam_idx

	cam_params["device"] = systems[cam_make]["deviceList"][cam_idx]
	cam_params = unicam.LoadDevice(systems, params, cam_params)

	cam_params["cameraSerialNo"] = systems[cam_make]["serials"][cam_idx]

	print(
		"Configured {} -> device index {} serial# {} settings {}".format(
			cam_params["cameraName"],
			cam_idx,
			cam_params["cameraSerialNo"],
			cam_params["cameraSettings"],
		),
		flush=True,
	)

	return cam_params


def GetCameraIndex(systems, cam_params):
	cam_make = cam_params["cameraMake"]
	serials = systems[cam_make]["serials"]
	requested_serial = cam_params.get("cameraSerialNo", "None")

	if requested_serial != "None":
		requested_serial = str(requested_serial)
		if requested_serial not in serials:
			raise ValueError(
				"Requested camera serial {} for {} was not found. Available serials: {}".format(
					requested_serial,
					cam_params["cameraName"],
					serials,
				)
			)
		return serials.index(requested_serial)

	return cam_params["cameraSelection"]


def OptParams(cam_params):
	# Optionally, user provides a single string or a list of strings, equal in size to numCams
	# String is passed to all cameras. Else, each list item is passed to its respective camera
	for key in cam_params:
		if type(cam_params[key]) is list:
			if len(cam_params[key]) == cam_params["numCams"]:
				cam_params[key] = cam_params[key][cam_params["n_cam"]]
			elif key in ["digitalPins", "pulsePalChannels"]:
				continue
			else:
				logging.warning("{} size mismatch with numCams. Using list idx {}."\
						.format(key,cam_params["n_cam"]))
				cam_params[key] = cam_params[key][cam_params["n_cam"]]
	return cam_params


def CheckConfig(params, clargs):
	default_params = DefaultParams()
	for key,value in default_params.items():
		if key not in params.keys():
			params[key] = value

	auto_params = AutoParams(params, default_params)
	for key,value in auto_params.items():
		params[key] = value

	params = NormalizeFolderParams(params)

	invalid_keys = []
	for key in params.keys():
		if key not in clargs.__dict__.keys():
			invalid_keys.append(key)

	if len(invalid_keys) > 0:
		invalid_key_msg = [" %s," % key for key in invalid_keys]
		msg = "Unrecognized keys in the config: %s" % "".join(invalid_key_msg)
		raise ValueError(msg)

	return params


def LoadConfig(config_path):
	try:
		with open(config_path, "rb") as f:
			config = yaml.safe_load(f)
	except Exception as e:
		logging.error('Caught this error at configurator.py LoadConfig: {}. Check your config path!'.format(e))
		raise
	return config


def CombineConfigAndClargs(clargs):
	params = LoadConfig(clargs.config)
	params = CheckConfig(params, clargs)
	for key, value in clargs.__dict__.items():
		if value is not None:
			params[key] = value
	params = NormalizeFolderParams(params)
	return params


def ParseClargs(parser):
	parser.add_argument(
		"config", metavar="config", help="Campy configuration .yaml file.",
	)

	# Recording arguments
	parser.add_argument(
		"--saveFolder", 
		dest="saveFolder", 
		help="Folder in which to save videos and session metadata.",
	)
	parser.add_argument(
		"--videoFolder", 
		dest="videoFolder", 
		help="Deprecated alias for saveFolder.",
	)
	parser.add_argument(
		"--videoFilename", 
		dest="videoFilename", 
		help="Name for video output file.",
	)
	parser.add_argument(
		"--frameRate", 
		dest="frameRate",
		type=float, 
		help="Frame rate equal to trigger frequency.",
	)
	parser.add_argument(
		"--recTimeInSec",
		dest="recTimeInSec",
		type=float,
		help="Recording time in seconds.",
	)    
	parser.add_argument(
		"--infiniteRecording",
		dest="infiniteRecording",
		type=bool,
		help="If True, record until Ctrl+C instead of stopping at recTimeInSec.",
	)
	parser.add_argument(
		"--numCams", 
		dest="numCams", 
		type=int, 
		help="Number of cameras.",
	)
	parser.add_argument(
		"--cameraNames", 
		dest="cameraNames", 
		type=ast.literal_eval, 
		help="Names assigned to the cameras in the order of cameraSelection.",
	)
	parser.add_argument(
		"--cameraSelection",
		dest="cameraSelection",
		type=int,
		help="Selects and orders camera indices to include in the recording. \
				List length must be equal to numCams",
	)

	# Camera arguments. May be specific to particular camera make
	parser.add_argument(
		"--cameraMake", 
		dest="cameraMake", 
		type=ast.literal_eval,
		help="Company that produced the camera. Currently supported: 'basler', 'flir'.",
	)
	parser.add_argument(
		"--cameraSettings", 
		dest="cameraSettings",
		type=ast.literal_eval, 
		help="Path to camera settings file.",
	)
	parser.add_argument(
		"--cameraSerialNo",
		dest="cameraSerialNo",
		type=ast.literal_eval,
		help="Camera serial number, or list of serial numbers, to map configs to devices deterministically.",
	)
	parser.add_argument(
		"--frameHeight", 
		dest="frameHeight",
		type=int, 
		help="Frame height in pixels.",
	)
	parser.add_argument(
		"--frameWidth", 
		dest="frameWidth",
		type=int, 
		help="Frame width in pixels.",
	)
	parser.add_argument(
		"--cameraDebug", 
		dest="cameraDebug",
		type=bool, 
		help="Flag to turn on camera debug mode.",
	)
	parser.add_argument(
		"--grabTimeoutInMs",
		dest="grabTimeoutInMs",
		type=int,
		help="Timeout in milliseconds to wait for the next grabbed frame.",
	)
	parser.add_argument(
		"--cameraTrigger", 
		dest="cameraTrigger",
		type=ast.literal_eval, 
		help="String indicating trigger input to camera (e.g. 'Line3').",
	)
	parser.add_argument(
		"--cameraOut", 
		dest="cameraOut",
		type=ast.literal_eval, 
		help="Camera output line for exposure active signal (e.g. 'Line3').",
	)
	parser.add_argument(
		"--cameraOutSource",
		dest="cameraOutSource",
		type=ast.literal_eval,
		help="Basler output signal source for cameraOut (e.g. 'ExposureActive' or 'FrameActive').",
	)
	parser.add_argument(
		"--cameraExposureTimeInUs", 
		dest="cameraExposureTimeInUs",
		type=int, 
		help="Exposure time (in microseconds) for each camera frame.",
	)
	parser.add_argument(
		"--cameraGain", 
		dest="cameraGain",
		type=float, 
		help="Intensity gain applied to each camera frame.",
	)
	parser.add_argument(
		"--disableGamma", 
		dest="disableGamma",
		type=bool, 
		help="Whether to disable gamma (default: True).",
	)
	parser.add_argument(
		"--bufferMode", 
		dest="bufferMode",
		type=ast.literal_eval, 
		help="Type of buffer to use in camera (default: 'OldestFirst').",
	)
	parser.add_argument(
		"--bufferSize", 
		dest="bufferSize",
		type=int, 
		help="Size of buffer to use in camera in frames (default: 100).",
	)

	# ffmpeg arguments
	parser.add_argument(
		"--ffmpegPath",
		dest="ffmpegPath",
		help="Location of ffmpeg binary for imageio.",
	)
	parser.add_argument(
		"--ffmpegLogLevel",
		dest="ffmpegLogLevel",
		type=ast.literal_eval,
		help="Sets verbosity level for ffmpeg logging. ('quiet' (no warnings), \
			'warning', 'info' (real-time stats)).",
	)
	parser.add_argument(
		"--pixelFormatInput",
		dest="pixelFormatInput",
		type=ast.literal_eval,
		help="Pixel format input. Use 'rgb24' for RGB or 'bayer_bggr8' for 8-bit bayer pattern.",
	)
	parser.add_argument(
		"--pixelFormatOutput",
		dest="pixelFormatOutput",
		type=ast.literal_eval,
		help="Pixel format output. Use 'rgb0' for best results.",
	)
	parser.add_argument(
		"--gpuID",
		dest="gpuID",
		type=int,
		help="List of integers assigning the gpu index to stream each camera. \
			Set to -1 to stream with CPU.",
	)
	parser.add_argument(
		"--gpuMake",
		dest="gpuMake",
		type=ast.literal_eval,
		help="Company that produced the GPU. Currently supported: 'nvidia', 'amd', 'intel' (QuickSync).",
	)
	parser.add_argument(
		"--codec",
		dest="codec",
		type=ast.literal_eval,
		help="Video codec for compression Currently supported: 'h264', 'h265' (hevc).",
	)
	parser.add_argument(
		"--quality",
		dest="quality",
		type=int,
		help="Compression quality. Lower number is less compression and larger files. \
			'23' is visually lossless.",
	)
	parser.add_argument(
		"--preset",
		dest="preset",
		type=ast.literal_eval,
		help="Compression preset (e.g. 'slow', 'fast', 'veryfast'). \
				Incorrect settings may break the pipe. Test with ffmpegLogLevel 'warning' or 'info'.",
	)

	# Display and CLI feedback arguments
	parser.add_argument(
		"--chunkLengthInSec",
		dest="chunkLengthInSec",
		type=float,
		help="Length of video chunks in seconds for reporting recording progress.",
	)
	parser.add_argument(
		"--displayFrameRate",
		dest="displayFrameRate",
		type=float,
		help="Display frame rate in Hz. Max ~30.",
	)
	parser.add_argument(
		"--displayDownsample",
		dest="displayDownsample",
		type=int,
		help="Downsampling factor for displaying images.",
	)
	parser.add_argument(
		"--guiPreviewEnabled",
		dest="guiPreviewEnabled",
		type=bool,
		help="If True, write latest preview images for the Qt GUI.",
	)
	parser.add_argument(
		"--guiPreviewFrameRate",
		dest="guiPreviewFrameRate",
		type=float,
		help="GUI preview image update rate in Hz.",
	)
	parser.add_argument(
		"--guiPreviewFolder",
		dest="guiPreviewFolder",
		help="Folder where GUI preview images are written.",
	)
	parser.add_argument(
		"--guiStopFile",
		dest="guiStopFile",
		help="File path used by the GUI to request graceful acquisition stop.",
	)
	parser.add_argument(
		"--guiCameraControlFile",
		dest="guiCameraControlFile",
		help="File path used by the GUI to send runtime camera control updates.",
	)

	# Microcontroller triggering arguments
	parser.add_argument(
		"--triggerController",
		dest="triggerController",
		type=ast.literal_eval,
		help="Microcontroller make for camera triggering. Currently supported: 'arduino', 'pulsepal'.",
	)
	parser.add_argument(
		"--startArduino",
		dest="startArduino",
		type=bool,
		help="If True, start Arduino after initializing cameras.",
	)
	parser.add_argument(
		"--startTriggerController",
		dest="startTriggerController",
		type=bool,
		help="If True, start the selected trigger controller.",
	)
	parser.add_argument(
		"--waitForTriggerStart",
		dest="waitForTriggerStart",
		type=bool,
		help="If True, wait for all cameras to arm, then prompt before starting triggers.",
	)
	parser.add_argument(
		"--serialPort",
		dest="serialPort",
		type=ast.literal_eval,
		help="Serial port for communicating with Arduino.",
	)
	parser.add_argument(
		"--digitalPins",
		dest="digitalPins",
		type=int,
		help="Digital pins on microcontroller board for sending TTL camera triggers.",
	)
	parser.add_argument(
		"--pulsePalPythonPath",
		dest="pulsePalPythonPath",
		type=ast.literal_eval,
		help="Optional folder containing PulsePal.py.",
	)
	parser.add_argument(
		"--pulsePalPort",
		dest="pulsePalPort",
		type=ast.literal_eval,
		help="Serial port for communicating with Pulse Pal.",
	)
	parser.add_argument(
		"--pulsePalChannels",
		dest="pulsePalChannels",
		type=ast.literal_eval,
		help="Pulse Pal output channels used for camera TTL triggers.",
	)
	parser.add_argument(
		"--pulseFrequencyHz",
		dest="pulseFrequencyHz",
		type=float,
		help="Pulse Pal output frequency in Hz.",
	)
	parser.add_argument(
		"--pulseHighTimeSec",
		dest="pulseHighTimeSec",
		type=float,
		help="Pulse Pal TTL high time in seconds.",
	)
	parser.add_argument(
		"--pulseTrainDurationSec",
		dest="pulseTrainDurationSec",
		type=float,
		help="Pulse Pal finite train duration in seconds.",
	)
	parser.add_argument(
		"--pulsePalContinuous",
		dest="pulsePalContinuous",
		type=bool,
		help="If True, Pulse Pal channels run continuously until stopped.",
	)
	parser.add_argument(
		"--pulsePalVoltage",
		dest="pulsePalVoltage",
		type=float,
		help="Pulse Pal phase 1 voltage.",
	)
	parser.add_argument(
		"--pulsePalRestingVoltage",
		dest="pulsePalRestingVoltage",
		type=float,
		help="Pulse Pal resting voltage.",
	)
	parser.add_argument(
		"--pulsePalTriggerChannel",
		dest="pulsePalTriggerChannel",
		type=int,
		help="Pulse Pal trigger channel to link when hardware trigger input is used.",
	)
	parser.add_argument(
		"--enableGPIOTimestampLogging",
		dest="enableGPIOTimestampLogging",
		type=bool,
		help="If True, log Neurologger GPIO timestamps into the session folder.",
	)
	parser.add_argument(
		"--gpioSerialPort",
		dest="gpioSerialPort",
		type=ast.literal_eval,
		help="Serial port for the Neurologger GPIO interface board.",
	)
	parser.add_argument(
		"--gpioBaudRate",
		dest="gpioBaudRate",
		type=int,
		help="Baud rate for the Neurologger GPIO interface board.",
	)
	parser.add_argument(
		"--gpioLogFilename",
		dest="gpioLogFilename",
		type=ast.literal_eval,
		help="Filename for the session-level GPIO timestamp log.",
	)

	return parser.parse_args()

