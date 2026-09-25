# -*- mode: python ; coding: utf-8 -*-

import platform

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


hiddenimports = [
    "dashscope",
    "dashscope.files",
    "dashscope.audio",
    "dashscope.audio.asr",
    "dashscope.audio.asr.transcription",
]
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("openai")
hiddenimports += collect_submodules("subtitle_agent_app")

windows_arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64"}.get(platform.machine().lower())
if windows_arch is None:
    raise SystemExit("Windows package architecture is unsupported: %s" % platform.machine())
aligner_dir = "subtitle_agent_app/cpp-ort-aligner-windows-%s" % windows_arch

datas = [
    ("subagent.png", "."),
    (aligner_dir, aligner_dir),
] + collect_data_files("zhconv")

analysis = Analysis(
    ["subtitle_agent_app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="Subtitle Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    exclude_binaries=True,
    console=False,
)

cli_exe = EXE(
    pyz,
    analysis.scripts,
    [],
    name="Subtitle Agent CLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    exclude_binaries=True,
    console=True,
)

coll = COLLECT(
    exe,
    cli_exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Subtitle Agent",
)
