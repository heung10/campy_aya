# Vendored Third-Party Modules

This folder contains optional third-party modules that make lab setup easier when
the matching hardware Python package is not installed globally.

## PulsePal

`PulsePal.py` and `ArCOM.py` are copied from the Sanworks PulsePal Python 3
support files. They are part of the Sanworks PulsePal repository and are
licensed under GPLv3 according to their source headers.

Campy loads these files only as a fallback after first trying a normal
`from PulsePal import PulsePalObject` import. If you prefer to keep PulsePal
outside this repo, set `pulsePalPythonPath` in the YAML config to the folder
containing `PulsePal.py`.
