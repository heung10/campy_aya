# campy for AyA Lab

Multi-camera Basler recording pipeline for AyA Lab experiments, with PulsePal
trigger control, Neurologger GPIO timestamp logging, and a PyQt GUI.

Original campy project: https://github.com/ksseverson57/campy

## External Requirements

Install these once on each acquisition computer:

- Basler pylon / pylon Viewer, tested with pylon 7.1.
- Basler camera drivers and network/USB setup.
- PulsePal USB driver if Windows does not recognize the device.
- Neurologger GPIO board USB driver if Windows does not recognize the device.
- NVIDIA/AMD/Intel GPU driver if using hardware video encoding.

The Python environment handles normal Python dependencies, `imageio-ffmpeg`,
the GUI, serial communication, and pypylon.

## Setup

From the repo root:

```powershell
conda env create -f environment.yml
conda activate campy
pip install -e .
```

If the environment already exists:

```powershell
conda env update --name campy --file environment.yml --prune
conda activate campy
pip install -e .
```

There is also a helper:

```powershell
.\tools\setup_windows_env.ps1
```

## Run The GUI

```powershell
conda activate campy
campy-gui
```

Or launch with a config already loaded:

```powershell
campy-gui configs\GPIO_test\campy_config_1camera_gpio.yaml
```

Direct module launch also works:

```powershell
python -m campy.gui.app configs\GPIO_test\campy_config_1camera_gpio.yaml
```

## Config Path Simplification

Configs should avoid computer-specific paths where possible:

```yaml
ffmpegPath: auto
pulsePalPythonPath: auto
```

`ffmpegPath: auto` searches:

- the `imageio-ffmpeg` bundled binary
- the active conda environment
- system `PATH`

`pulsePalPythonPath: auto` searches:

- a normally installed/importable `PulsePal.py`
- the vendored fallback in `campy/vendor`
- an explicit folder if `pulsePalPythonPath` is set to a real path

## Current GPIO Camera-Output Test

For the current one-camera GPIO synchronization test:

```yaml
cameraTrigger: Line2
cameraOut: Line3
cameraOutSource: ExposureActive
enableGPIOTimestampLogging: true
```

Hardware meaning:

- PulsePal trigger goes to camera `Line2`.
- Camera `Line3` outputs `ExposureActive`.
- Camera `Line3` output goes to the Neurologger GPIO board.
- GPIO ground must be shared correctly.

## Evaluate A Session

After recording, summarize camera/GPIO counts and camera-vs-GPIO datetime
alignment:

```powershell
campy-evaluate C:\Users\Cornell\Desktop\Basler\campy_test\GPIO_test\06292026
```

By default this removes GPIO events closer than 1 ms apart as duplicate/noise
events, while preserving the raw `gpio_log.csv`.

## Build A Windows GUI EXE

The repo includes first-pass PyInstaller scaffolding. From an activated `campy`
environment:

```powershell
.\tools\build_windows_gui_exe.ps1
```

Expected output:

```text
dist\campy-gui\campy-gui.exe
```

The exe build is intentionally separate from normal development. Vendor camera
drivers, pylon runtime, serial drivers, and GPU drivers still need to be
installed on the target computer.

## Notes

The `campy/vendor` folder contains optional third-party PulsePal support files
from Sanworks. Those files are GPLv3 according to their source headers and are
kept separate from the MIT-licensed campy code.

## Template Configs

Starter templates live in:

```text
configs/templates/1camera_gpio_template.yaml
configs/templates/2camera_gpio_template.yaml
```

They are meant to be copied and edited for each computer / rig.
