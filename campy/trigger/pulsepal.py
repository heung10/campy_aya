"""
Pulse Pal trigger controller support.
"""

import sys


def _load_pulsepal(params):
	if params["pulsePalPythonPath"] != "None":
		if params["pulsePalPythonPath"] not in sys.path:
			sys.path.append(params["pulsePalPythonPath"])
	from PulsePal import PulsePalObject
	return PulsePalObject


def _pulse_period(params):
	period = 1.0 / float(params["pulseFrequencyHz"])
	high_time = float(params["pulseHighTimeSec"])
	low_time = period - high_time
	if low_time <= 0:
		raise ValueError(
			"pulseHighTimeSec must be shorter than one pulse period at pulseFrequencyHz."
		)
	return high_time, low_time


def _trigger_outputs(pp, channels):
	flags = [1 if ch in channels else 0 for ch in range(1, 5)]
	try:
		pp.triggerOutputChannels(*flags)
	except TypeError:
		pp.triggerOutputChannels(channels)


def StartTriggers(systems, params):
	PulsePalObject = _load_pulsepal(params)
	pp = PulsePalObject(params["pulsePalPort"])
	channels = [int(ch) for ch in params["pulsePalChannels"]]
	high_time, low_time = _pulse_period(params)

	for ch in channels:
		pp.programOutputChannelParam("phase1Voltage", ch, params["pulsePalVoltage"])
		pp.programOutputChannelParam("restingVoltage", ch, params["pulsePalRestingVoltage"])
		pp.programOutputChannelParam("phase1Duration", ch, high_time)
		pp.programOutputChannelParam("interPulseInterval", ch, low_time)
		pp.programOutputChannelParam("pulseTrainDuration", ch, params["pulseTrainDurationSec"])
		pp.programOutputChannelParam("pulseTrainDelay", ch, 0)
		pp.programOutputChannelParam("customTrainID", ch, 0)
		pp.programOutputChannelParam("linkTriggerChannel1", ch, 0)
		pp.programOutputChannelParam("linkTriggerChannel2", ch, 0)
		pp.setContinuousLoop(ch, 1 if params["pulsePalContinuous"] else 0)

	pp.programTriggerChannelParam("triggerMode", params["pulsePalTriggerChannel"], 0)
	_trigger_outputs(pp, channels)

	systems["pulsepal"] = pp
	print(
		"Pulse Pal on {} started channels {} at {} Hz ({} sec high, {} sec low).".format(
			params["pulsePalPort"],
			channels,
			params["pulseFrequencyHz"],
			high_time,
			low_time,
		),
		flush=True,
	)
	return systems


def StopTriggerOutputs(systems):
	pp = systems.get("pulsepal")
	if pp is None:
		return

	print("Stopping Pulse Pal outputs...", flush=True)
	try:
		pp.abortPulseTrains()
	except Exception:
		pass


def CloseTriggerController(systems):
	pp = systems.get("pulsepal")
	if pp is None:
		return

	print("Disconnecting Pulse Pal...", flush=True)
	try:
		pp.disconnect()
	except Exception:
		pass
	systems["pulsepal"] = None


def StopTriggers(systems):
	StopTriggerOutputs(systems)
	CloseTriggerController(systems)
