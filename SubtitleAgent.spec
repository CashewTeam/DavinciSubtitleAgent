# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


hiddenimports = []
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("dashscope")
hiddenimports += collect_submodules("funasr")
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
    analysis.binaries,
    analysis.datas,
    [],
    name="Subtitle Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

app = BUNDLE(
    exe,
    name="Subtitle Agent.app",
    icon=None,
    bundle_identifier="com.cashewteam.subtitleagent",
)
