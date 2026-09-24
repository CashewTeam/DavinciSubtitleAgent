"""DaVinci Resolve Scripts-menu launcher for Subtitle Agent."""

import os
import shutil
import subprocess
import sys


APP_NAME = "Subtitle Agent"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SCRIPT_PATH = os.environ.get("SUBTITLE_AGENT_SCRIPT") or os.path.join(
    SCRIPT_DIR, "subtitle_agent_app.py"
)


def _app_candidates():
    configured = os.environ.get("SUBTITLE_AGENT_EXE")
    candidates = [configured] if configured else []
    if os.name == "nt":
        candidates.extend(
            [
                os.path.join(SCRIPT_DIR, "dist", "windows", APP_NAME, APP_NAME + ".exe"),
                os.path.join(SCRIPT_DIR, "dist", APP_NAME, APP_NAME + ".exe"),
                os.path.join(SCRIPT_DIR, APP_NAME + ".exe"),
            ]
        )
    else:
        candidates.extend(
            [
                os.path.join(SCRIPT_DIR, APP_NAME + ".app"),
                os.path.join(SCRIPT_DIR, "dist", APP_NAME + ".app"),
                os.path.join("/Applications", APP_NAME + ".app"),
            ]
        )
    return [path for path in candidates if path]


def _config_path():
    if os.name == "nt":
        base_dir = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local"
        )
    else:
        base_dir = os.path.expanduser("~/Library/Application Support")
    return os.path.join(base_dir, "SubtitleAgent", "subtitle_agent_config.json")


def _launch_app(path):
    if os.name == "nt":
        subprocess.Popen([path], cwd=os.path.dirname(path))
    else:
        subprocess.Popen(["open", path], cwd=SCRIPT_DIR)


def _source_command():
    if os.name != "nt":
        return [sys.executable or "python3", APP_SCRIPT_PATH]

    configured_python = os.environ.get("SUBTITLE_AGENT_PYTHON")
    if configured_python:
        return [configured_python, APP_SCRIPT_PATH]

    launcher = shutil.which("py")
    if launcher:
        return [launcher, "-3.12", APP_SCRIPT_PATH]

    python = shutil.which("python")
    if python:
        return [python, APP_SCRIPT_PATH]
    raise RuntimeError("Build the Windows app or install Python 3.12 and add the py launcher to PATH.")


def main():
    for candidate in _app_candidates():
        exists = os.path.isfile(candidate) if os.name == "nt" else os.path.isdir(candidate)
        if exists:
            _launch_app(candidate)
            return

    if os.path.isfile(APP_SCRIPT_PATH):
        env = os.environ.copy()
        env["SUBTITLE_AGENT_CONFIG_PATH"] = _config_path()
        subprocess.Popen(_source_command(), cwd=SCRIPT_DIR, env=env)
        return

    raise RuntimeError(
        "Subtitle Agent was not found. Build the app or set SUBTITLE_AGENT_EXE to its executable path."
    )


if __name__ == "__main__":
    main()
