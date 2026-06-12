#!/usr/bin/env python3

import os
import subprocess
import sys


APP_NAME = "Subtitle Agent"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_SUPPORT_DIR = os.path.expanduser("~/Library/Application Support/SubtitleAgent")
CONFIG_PATH = os.path.join(APP_SUPPORT_DIR, "subtitle_agent_config.json")
APP_SCRIPT_PATH = os.path.join(SCRIPT_DIR, "subtitle_agent_app.py")

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
    subprocess.Popen([sys.executable or "python3", APP_SCRIPT_PATH], cwd=SCRIPT_DIR, env=env)


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
