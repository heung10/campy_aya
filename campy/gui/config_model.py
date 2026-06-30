"""
Small YAML model helpers for the campy GUI.
"""

from __future__ import print_function

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCALAR_TYPES = (str, int, float, bool, type(None))


class CampyYamlDumper(yaml.SafeDumper):
    pass


def _represent_list_inline_when_simple(dumper, data):
    simple = all(isinstance(item, SCALAR_TYPES) for item in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=simple)


CampyYamlDumper.add_representer(list, _represent_list_inline_when_simple)


@dataclass
class CampyConfig:
    data: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    @property
    def loaded(self):
        return self.path is not None and bool(self.data)


def load_config(path):
    config_path = Path(path).expanduser().resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a YAML mapping.")
    return CampyConfig(data=data, path=config_path)


def save_config(config, path=None):
    output_path = Path(path or config.path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.dump(config.data, handle, Dumper=CampyYamlDumper, sort_keys=False, default_flow_style=False)
    config.path = output_path
    return output_path


def get_value(data, key, default=None):
    value = data.get(key, default)
    return default if value is None else value


def set_if_present(data, key, value):
    data[key] = value
    if key == "saveFolder":
        # Keep the legacy alias aligned with the clearer GUI field.
        data["videoFolder"] = value


def camera_names(data):
    count = int(get_value(data, "numCams", 1) or 1)
    names = data.get("cameraNames")
    if isinstance(names, list):
        clean = [str(name) for name in names]
    elif isinstance(names, str) and names.strip():
        clean = [part.strip() for part in names.split(",") if part.strip()]
    else:
        clean = []

    while len(clean) < count:
        clean.append("Camera{}".format(len(clean) + 1))
    return clean[:count]


def set_camera_names(data, names_text):
    names = [part.strip() for part in str(names_text).split(",") if part.strip()]
    if names:
        data["cameraNames"] = names


def resolved_save_folder(data):
    folder = data.get("saveFolder") or data.get("videoFolder") or "./test"
    path = Path(str(folder)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def validate_config(data):
    messages = []
    num_cams = int(get_value(data, "numCams", 1) or 1)
    if num_cams < 1:
        messages.append(("error", "numCams must be at least 1."))
    if num_cams > 6:
        messages.append(("warning", "The first GUI draft previews/statuses the first 6 cameras."))

    save_folder = data.get("saveFolder") or data.get("videoFolder")
    if not save_folder:
        messages.append(("error", "saveFolder is empty."))

    for key in ["recTimeInSec", "frameRate", "pulseFrequencyHz"]:
        try:
            if float(get_value(data, key, 0)) <= 0:
                messages.append(("error", "{} must be positive.".format(key)))
        except Exception:
            messages.append(("error", "{} must be numeric.".format(key)))

    if get_value(data, "enableGPIOTimestampLogging", False) and not data.get("gpioSerialPort"):
        messages.append(("error", "GPIO logging is enabled, but gpioSerialPort is empty."))

    if get_value(data, "startTriggerController", False):
        if str(get_value(data, "triggerController", "")).lower() == "pulsepal" and not data.get("pulsePalPort"):
            messages.append(("error", "PulsePal trigger is enabled, but pulsePalPort is empty."))

    names = camera_names(data)
    if len(names) != num_cams:
        messages.append(("warning", "cameraNames will be padded/truncated to match numCams."))

    if not messages:
        messages.append(("ok", "Config looks ready for a first-pass GUI launch."))
    return messages


def messages_to_text(messages):
    return "\n".join("[{}] {}".format(level.upper(), message) for level, message in messages)
