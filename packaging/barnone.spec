# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bar None (Windows).

Build from the repository root:

    pyinstaller packaging\\barnone.spec --noconfirm --clean

or simply run packaging\\build.bat.  Output: dist\\BarNone\\ containing
BarNone.exe (GUI), BarNone-cli.exe (console) and the runtime `_internal\\`.
"""

import os

SPECDIR = SPECPATH  # directory holding this spec
ROOT = os.path.abspath(os.path.join(SPECDIR, ".."))
ASSETS = os.path.join(ROOT, "assets")
ICON = os.path.join(ASSETS, "icon.ico")

# Window/exe icon — only if the artwork has been converted yet
# (python packaging/make_icon.py).
icon = ICON if os.path.exists(ICON) else None

datas = []
for filename in ("icon.ico", "icon.png"):
    path = os.path.join(ASSETS, filename)
    if os.path.exists(path):
        datas.append((path, "assets"))

a = Analysis(
    [os.path.join(ROOT, "src", "main.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# librosa's ecosystem ships data files and C extensions that PyInstaller's
# default hooks don't always catch — numba/llvmlite are the classic gap.
from PyInstaller.utils.hooks import collect_all


def _toc(entries, typecode):
    """collect_* helpers return 2-tuples; TOCs need (dest, src, typecode)."""
    out = []
    for entry in entries:
        if len(entry) == 2:
            out.append((entry[0], entry[1], typecode))
        else:
            out.append(entry)
    return out


for package in ("librosa", "soundfile", "numba", "llvmlite"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    a.datas += _toc(pkg_datas, "DATA")
    a.binaries += _toc(pkg_binaries, "BINARY")
    a.hiddenimports += pkg_hidden

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarNone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    version=os.path.join(SPECDIR, "version_info.py"),
)

exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BarNone-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=icon,
    version=os.path.join(SPECDIR, "version_info_cli.py"),
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BarNone",
)
