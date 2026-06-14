import sys
import time

# Change this path if your PulsePal.py is somewhere else
sys.path.append(r"C:\Users\Cornell\Downloads\PulsePal-master\PulsePal-master\Python\Python3")

from PulsePal import PulsePalObject

# Change COM3 to your actual Pulse Pal port
pp = PulsePalObject("COM10")

# Output channels to use
channels = [1, 2, 3, 4]

# Pulse parameters: 40 Hz, 5 ms high, 20 ms low
phase1_voltage = 5          # 5 V TTL
resting_voltage = 0         # 0 V baseline
phase1_duration = 0.005     # 5 ms high
inter_pulse_interval = 0.020  # 20 ms low
pulse_train_duration = 1    # arbitrary; continuous loop overrides normal ending

for ch in channels:
    # Same pulse on every output channel
    pp.programOutputChannelParam("phase1Voltage", ch, phase1_voltage)
    pp.programOutputChannelParam("restingVoltage", ch, resting_voltage)
    pp.programOutputChannelParam("phase1Duration", ch, phase1_duration)
    pp.programOutputChannelParam("interPulseInterval", ch, inter_pulse_interval)
    pp.programOutputChannelParam("pulseTrainDuration", ch, pulse_train_duration)
    pp.programOutputChannelParam("pulseTrainDelay", ch, 0)

    # Use normal parametric pulse train, not custom train
    pp.programOutputChannelParam("customTrainID", ch, 0)

    # Link physical Trigger Channel 1 to this output channel
    pp.programOutputChannelParam("linkTriggerChannel1", ch, 1)

    # Optional: make sure Trigger Channel 2 does not trigger it
    pp.programOutputChannelParam("linkTriggerChannel2", ch, 0)

    # Infinite/continuous mode
    pp.setContinuousLoop(ch, 1)

# Usually normal trigger mode is fine.
# If needed, explicitly set Trigger Channel 1 to normal mode:
pp.programTriggerChannelParam("triggerMode", 1, 0)

print("Ready.")
print("Now send a TTL pulse into Pulse Pal Trigger Channel 1.")
print("Outputs 1-4 should start the same 40 Hz pulse train continuously.")

try:
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    print("Stopping Pulse Pal outputs...")
    pp.abortPulseTrains()

    for ch in channels:
        pp.setContinuousLoop(ch, 0)

    pp.disconnect()
    print("Disconnected.")