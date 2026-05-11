# Basler Multi-Camera Recording Setup Handoff

## Overview

I am building a synchronized multi-camera recording system for animal behavior and neuroscience experiments. The goal is to record from multiple Basler GigE cameras together with synchronized neural and behavioral data.

I am now moving away from pylon Viewer for long recordings and want to use `campy` instead:
https://github.com/ksseverson57/campy

I want this document to summarize my current hardware, what has already been solved, what problems I encountered, and what I want to achieve next.

---

## Experimental / Technical Goal

I need a robust recording pipeline for:

- 4 Basler GigE cameras
- synchronized hardware triggering at 40 Hz
- long-duration recordings (at least 1 hour, ideally 2+ hours)
- reliable frame saving with minimal or zero dropped frames
- precise frame timing that can later be compared with neural acquisition and behavioral events

The most important requirements are:

1. all cameras should acquire one frame per trigger pulse at 40 Hz
2. recorded data should be saved reliably for long sessions
3. per-frame timing should be checkable afterward
4. the solution should be stable enough for real experiments, not just short tests

---

## Hardware

### Cameras
- Basler `a2A1920-51gmPRO`
- GigE cameras
- currently using 4 cameras

### Computer
Windows PC:
- 13th Gen Intel Core i7-13700K
- 64 GB RAM
- Windows 64-bit

### Interfaces / acquisition
- Basler GigE interface card
- pulse generator for camera trigger
- may also use Open Ephys or Intan for neural acquisition
- may also use Bpod for behavior
- may also have Pulse Pal available

### Other neuroscience-related hardware in the broader setup
- Basler cameras
- Neuronexus / Cambridge Neurotech silicon probes
- custom neurologger
- Intan or Open Ephys
- Arduino / microcontroller
- NI devices may be available
- Bpod for behavior control

---

## Current Synchronization Logic

### Triggering
I successfully configured the cameras to use external trigger input and acquire at 40 Hz.

The trigger is:
- 40 Hz
- true 25 ms period
- example: 5 ms high + 20 ms low

Important earlier mistake:
- I initially confused 5 ms high + 25 ms interval with 40 Hz
- that is actually 33.3 Hz
- now fixed

### Camera trigger settings
The working setup is hardware trigger with:
- `TriggerSelector = FrameStart`
- `TriggerMode = On`
- `TriggerSource = Line2`
- `TriggerActivation = RisingEdge`
- `AcquisitionMode = Continuous`
- `ExposureAuto = Off`
- fixed exposure time

Typical exposure used:
- `Exposure Time = 20000 us`

### Important wiring lesson
I had a major issue because the trigger ground was wrong.

For this camera:
- `Line2` is GPIO input
- GPIO trigger ground must be the GPIO ground
- using the wrong ground caused `RisingEdge` not to work

Symptoms before fix:
- `LevelHigh` seemed to work
- `RisingEdge` did not work
- frame rate did not follow pulse frequency
- line status behavior was confusing

After fixing the correct ground reference, hardware triggering worked properly.

---

## IP / Network Setup

I am using one camera per Ethernet port on the Basler GigE interface card.

Desired network scheme was:

- Ethernet 2 -> adapter `192.168.2.2`, camera `192.168.2.3`
- Ethernet 3 -> adapter `192.168.3.2`, camera `192.168.3.3`
- Ethernet 4 -> adapter `192.168.4.2`, camera `192.168.4.3`
- Ethernet 5 -> adapter `192.168.5.2`, camera `192.168.5.3`

I had trouble with unreachable cameras and IP assignment in pylon.
At one point, some cameras appeared in bandwidth manager but could not be opened.
There were errors like:
- socket operation attempted to an unreachable network
- could not create camera

Important lesson:
- the Windows Ethernet adapter naming was confusing
- the physical port and Windows adapter label did not always match my assumption
- some cameras had stale IP states
- one camera may have been faulty or at least unreliable

Eventually I managed to get 4 working cameras.

---

## pylon Viewer Experience

I used pylon Viewer extensively for testing and tuning.

### What worked
- configuring hardware trigger
- verifying Line2 trigger input
- confirming 40 Hz acquisition
- testing 2 cameras, then 4 cameras
- setting chunk mode
- adjusting network settings like packet size and inter-packet delay

### What did not work well
Long-duration multi-camera recording in pylon Viewer became unreliable.

Observed problems:
- incomplete grab / incompletely grabbed buffer
- packet-related errors
- random cameras failing during longer recording
- one camera stopping after ~20 min
- frame loss
- which camera failed could change after buffer tweaks
- after changing buffers, problems moved from one camera to another instead of disappearing

This suggests the problem is not one wrong camera setting, but rather the overall multi-camera recording pipeline in pylon Viewer under load.

---

## Important Error Messages Encountered

### Trigger / wiring stage
Earlier, rising edge trigger did not work because the line wiring / ground was wrong.

### Multi-camera recording stage
A key error message was:

> The buffer was incompletely grabbed. This can be caused by performance problems of the network hardware used, i.e. network adapter, switch, or ethernet cable. To fix this, try increasing the camera's Inter-Packet Delay in the Transport Layer category to reduce the required bandwidth, and adjust the camera's Packet Size setting to the highest supported frame size.

Also:
- cameras sometimes stopped recording after long duration
- some cameras had a few missing frames in a short test
- long recordings could become unstable

---

## Chunk Data / Metadata

I enabled chunk mode in pylon.

Important chunk settings:
- `Chunk Mode Active = On`
- I looked at `Frame ID`
- I looked at `Chunk Timestamp Value`
- `Chunk Timestamp Selector = FrameStart`

However, because I was using pylon Viewer, I do not think the chunk metadata was automatically exported in an easy per-frame analysis format like CSV.
So I could see chunk data in the camera/grab context, but not easily analyze it afterward from the saved recording alone.

This is one of the reasons I want to move to a custom recording pipeline.

---

## Settings Comparison That Matters

I exported settings from two cameras (`cam2` and `cam3`) when `cam3` was the problematic one.

Main finding:
- camera acquisition settings were essentially matched
- trigger settings were matched
- ROI, mono8, exposure, trigger mode, packet size, inter-packet delay were basically similar

But the stream statistics were very different.

For example:
- problematic camera had much higher failed buffer count
- much higher buffer underrun count
- much higher failed packet count
- much higher resend counts

This strongly suggests:
- the real issue is transport / network / streaming robustness under load
- not just trigger settings

I also noticed firmware differences between cameras:
- not all cameras had the same firmware version

That may or may not matter, but it is a real difference.

---

## Network / Transport Tuning Already Tried

### Packet size
I started from packet size 1500 and tried increasing it.
Typical tested value:
- `Packet Size = 3000`

I also asked about jumbo-frame style larger packet sizes such as 6000 / 8192 / 9000, but I have not fully stabilized the system yet.

### Inter-packet delay
Typical values were around:
- `Inter-Packet Delay ~ 1400 ns`

I tried increasing transport margin.

### Buffers
I increased buffer-related settings as suggested.

Originally smaller values:
- `Maximum Number of Buffers = 15`
- `Event Grabber NumBuffer = 10`
- recording buffer around 100 frames

I later increased them to larger values.

But after increasing buffers:
- instability did not fully disappear
- sometimes the failing camera changed
- at one point cam3 was problematic
- later cam5 was problematic
- at another point three cameras had issues

This is a major reason I think pylon Viewer is not the right long-duration multi-camera recording solution for me.

---

## Why I Want To Switch To campy

I want to move to `campy` because:

1. it is designed for multi-camera recording
2. it supports Basler cameras
3. it appears to support hardware-triggered workflows
4. it may offer a more controllable and transparent acquisition pipeline than pylon Viewer
5. I want better control over:
   - frame saving
   - metadata saving
   - dropped frame detection
   - long-duration recording robustness

Repository:
https://github.com/ksseverson57/campy

---

## What Has Already Been Solved

These parts are already working and should not need to be reinvented unless necessary:

1. I can configure Basler external trigger mode successfully
2. I can run 4 cameras at fixed 40 Hz hardware triggering
3. I know the correct trigger wiring for the cameras now
4. I have a working pulse generator setup
5. I can connect multiple cameras through the Basler GigE interface card
6. I know that the key difficulty is not the 40 Hz trigger itself, but reliable streaming/saving over long recordings

---

## Current Hypothesis About the Main Problem

The main problem appears to be:

**Long-duration, multi-camera streaming and saving reliability on the PC side**

not:
- trigger timing itself
- basic external trigger configuration
- simple camera setup

Likely contributing factors:
- GigE transport instability under 4-camera load
- packet loss / resend burden
- pylon Viewer buffering/recording limitations for this use case
- possible per-port / per-camera variability
- maybe firmware or hardware differences among cameras
- maybe cable / connector / NIC path differences

---

## What I Want Codex To Help With

I want help transitioning to a more robust recording pipeline using `campy`.

### Main goals
1. understand how to configure `campy` for my 4-camera externally triggered 40 Hz setup
2. preserve reliable frame saving during long recordings
3. store enough per-frame metadata to check timing and dropped frames later
4. ideally compare saved frame timing against expected 40 Hz or external TTL timing
5. make the recording pipeline stable enough for real experiments

### Specific questions / tasks
Please help with:

- understanding how `campy` handles Basler cameras with external trigger
- determining whether `campy` can save frame timestamps / frame counters / metadata
- figuring out how to configure 4 synchronized cameras in `campy`
- deciding whether `campy` alone is enough or whether we should directly use `pypylon`
- designing a robust file output / metadata logging format
- checking whether FFmpeg compression in `campy` could help with long recordings
- identifying any likely incompatibilities between my Basler ace 2 Pro GigE cameras and `campy`
- recommending the safest validation test before using this in real experiments

---

## Desired Validation Plan

I want the final system to pass something like this:

1. 4 cameras connected
2. shared 40 Hz external trigger
3. 1-hour recording minimum
4. no crashes
5. frame count consistent with expected duration
6. minimal or zero dropped frames
7. saved metadata sufficient to identify:
   - frame number
   - frame timing
   - missing frames
8. ideally easy post hoc comparison with neural acquisition timestamps

---

## Nice-To-Have

If possible, I would also like:

- a recommendation on whether to use raw image sequence, compressed video, or something else
- a strategy to save chunk-like metadata with each frame
- a way to detect incomplete grabs and log them during acquisition
- a minimal stress-test script before the full experiment workflow

---

## Summary In One Sentence

The 40 Hz external triggering now works, but pylon Viewer is not reliable enough for long 4-camera recordings, so I want to move to `campy` (or a closely related custom Basler pipeline) and need help making it robust, metadata-rich, and suitable for synchronized neuroscience experiments.