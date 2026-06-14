"""
Trigger nexus
"""

import logging

def ImportTrigger(params):
	if params["triggerController"] == "Arduino" or params["triggerController"] == "arduino":
		import campy.trigger.arduino as trigger
	elif params["triggerController"] == "PulsePal" or params["triggerController"] == "pulsepal":
		import campy.trigger.pulsepal as trigger
	elif params["triggerController"] == "None" or params["triggerController"] == "none":
		import campy.trigger.arduino as trigger
	else:
		raise ValueError('The trigger controller you have selected is not supported.')
	return trigger


def TriggerControllerEnabled(params):
	return params["startArduino"] or params["startTriggerController"]


def StartTriggers(systems, params):
	if TriggerControllerEnabled(params):
		if params["triggerController"] != "None":
			trigger = ImportTrigger(params)
			systems = trigger.StartTriggers(systems, params)
	return systems


def StopTriggers(systems, params):
	if TriggerControllerEnabled(params):
		if params["triggerController"] != "None":
			trigger = ImportTrigger(params)
			trigger.StopTriggers(systems)
