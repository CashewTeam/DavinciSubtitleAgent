# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = [
    "dashscope",
    "dashscope.files",
    "dashscope.audio",
    "dashscope.audio.asr",
    "dashscope.audio.asr.transcription",
]
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("openai")

datas = [
    ("subtitle_agent/subtitle_agent_core.tool", "subtitle_agent"),
    ("subtitle_agent/subagent.png", "subtitle_agent"),
]

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

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Subtitle Agent",
)

app = BUNDLE(
    coll,
    name="Subtitle Agent.app",
    icon=None,
    bundle_identifier="com.cashewteam.subtitleagent",
)
