# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("campy")
hiddenimports += collect_submodules("serial")
hiddenimports += [
    "pypylon",
    "pypylon.pylon",
    "pypylon.genicam",
    "imageio_ffmpeg",
    "numpy",
    "scipy",
    "skimage",
    "yaml",
    "campy.vendor.PulsePal",
    "campy.vendor.ArCOM",
]

datas = []
datas += collect_data_files("imageio_ffmpeg")
datas += collect_data_files("campy.vendor")


a = Analysis(
    ["campy/gui/app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="campy-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="campy-gui",
)
