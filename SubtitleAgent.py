#!/usr/bin/env python3

import json
import os
import subprocess
import sys


APP_NAME = "Subtitle Agent"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/SubtitleAgent")
CONFIG_PATH = os.path.join(APP_SUPPORT_DIR, "subtitle_agent_config.json")
LEGACY_CONFIG_PATH = os.path.join(SCRIPT_DIR, "subtitle_agent", "subtitle_agent_config.json")
APP_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "subtitle_agent_app.py")


def _load_config():
    for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception:
                pass
    return {}


def _python_executable():
    config = _load_config()
    path = os.path.expanduser(config.get("python_path", "")).strip()
    if path:
        return path
    return sys.executable or "python3"


def _app_bundle_candidates():
    return [
        os.path.join(SCRIPT_DIR, "%s.app" % APP_NAME),
        os.path.join(SCRIPT_DIR, "dist", "%s.app" % APP_NAME),
        os.path.join("/Applications", "%s.app" % APP_NAME),
    ]


def _launch_app_bundle(path):
    subprocess.Popen(["open", path], cwd=SCRIPT_DIR)


def _launch_source_app():
    env = os.environ.copy()
    env["SUBTITLE_AGENT_CONFIG_PATH"] = CONFIG_PATH
    subprocess.Popen([_python_executable(), APP_SCRIPT_PATH], cwd=SCRIPT_DIR, env=env)


def main():
    for candidate in _app_bundle_candidates():
        if os.path.isdir(candidate):
            _launch_app_bundle(candidate)
            return
    if os.path.isfile(APP_SCRIPT_PATH):
        _launch_source_app()
        return
    raise RuntimeError("Subtitle Agent app was not found. Expected %s or a built %s.app bundle." % (APP_SCRIPT_PATH, APP_NAME))


if __name__ == "__main__":
    main()
