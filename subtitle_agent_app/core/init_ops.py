#!/usr/bin/env python3

import os
import shutil
import subprocess
import tempfile
from urllib.parse import quote

import requests

from .bootstrap import APP_SUPPORT_DIR, ensure_dir, worker_log
from .resolve_ops import ffmpeg_exe


MODEL_REPO = "csukuangfj2/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12"
MODEL_DIR_NAME = "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12"
MODEL_FILES = ("model.int8.onnx", "tokens.txt")
MODEL_BASE_URLS = (
    "https://hf-mirror.com/%s/resolve/main" % MODEL_REPO,
    "https://huggingface.co/%s/resolve/main" % MODEL_REPO,
)


def _model_target_dir():
    return os.path.join(os.path.expanduser(APP_SUPPORT_DIR), "models", MODEL_DIR_NAME)


def _is_valid_omnilingual_dir(path):
    path = os.path.abspath(os.path.expanduser(path or ""))
    return bool(path) and os.path.isdir(path) and all(os.path.isfile(os.path.join(path, name)) for name in MODEL_FILES)


def inspect_init_status(config=None):
    config = config or {}
    brew_path = shutil.which("brew")
    ffmpeg_path = ""
    ffmpeg_ready = False
    ffmpeg_error = ""
    try:
        ffmpeg_path = ffmpeg_exe()
        ffmpeg_ready = True
    except Exception as exc:
        ffmpeg_error = str(exc)

    configured_model_dir = os.path.abspath(os.path.expanduser(config.get("align_model_dir") or "")) if config.get("align_model_dir") else ""
    default_model_dir = _model_target_dir()
    model_dir = configured_model_dir if _is_valid_omnilingual_dir(configured_model_dir) else default_model_dir
    model_ready = _is_valid_omnilingual_dir(model_dir)

    return {
        "success": True,
        "brew_ready": bool(brew_path),
        "brew_path": brew_path or "",
        "ffmpeg_ready": ffmpeg_ready,
        "ffmpeg_path": ffmpeg_path,
        "ffmpeg_error": ffmpeg_error,
        "model_ready": model_ready,
        "model_dir": model_dir,
        "configured_model_dir": configured_model_dir,
        "model_repo": MODEL_REPO,
        "model_sources": list(MODEL_BASE_URLS),
    }


def install_ffmpeg(log_callback=None):
    logs = []

    def log(message):
        if log_callback:
            log_callback(message)
        else:
            worker_log(logs, message)

    brew_path = shutil.which("brew")
    if not brew_path:
        raise RuntimeError("Homebrew not found. Install Homebrew first, then rerun initialization.")
    try:
        current = ffmpeg_exe()
        return {"success": True, "installed": False, "ffmpeg_path": current, "logs": logs}
    except Exception:
        pass

    cmd = [brew_path, "install", "ffmpeg"]
    log("Running: %s" % " ".join(cmd))
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    try:
        for line in process.stdout or []:
            if line.strip():
                log(line.rstrip())
        return_code = process.wait()
    finally:
        if process.stdout:
            process.stdout.close()
    if return_code != 0:
        raise RuntimeError("brew install ffmpeg failed with exit code %s" % return_code)
    ffmpeg_path = ffmpeg_exe()
    log("ffmpeg ready: %s" % ffmpeg_path)
    return {"success": True, "installed": True, "ffmpeg_path": ffmpeg_path, "logs": logs}


def _download_file(url, target_path, log):
    response = requests.get(url, stream=True, timeout=(20, 600))
    response.raise_for_status()
    total = int(response.headers.get("content-length") or 0)
    downloaded = 0
    with open(target_path, "wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)
            downloaded += len(chunk)
            if total:
                log("Downloading %s: %.1f%%" % (os.path.basename(target_path), downloaded * 100.0 / total))


def download_alignment_model(config=None, log_callback=None):
    logs = []
    config = config or {}

    def log(message):
        if log_callback:
            log_callback(message)
        else:
            worker_log(logs, message)

    configured_dir = config.get("align_model_dir") or ""
    if _is_valid_omnilingual_dir(configured_dir):
        model_dir = os.path.abspath(os.path.expanduser(configured_dir))
        log("Model already ready: %s" % model_dir)
        return {"success": True, "model_dir": model_dir, "downloaded": False, "logs": logs}

    target_dir = _model_target_dir()
    if _is_valid_omnilingual_dir(target_dir):
        log("Model already ready: %s" % target_dir)
        return {"success": True, "model_dir": target_dir, "downloaded": False, "logs": logs}

    ensure_dir(os.path.dirname(target_dir))
    temp_dir = tempfile.mkdtemp(prefix="subtitle_agent_model_", dir=os.path.dirname(target_dir))
    try:
        errors = []
        for base_url in MODEL_BASE_URLS:
            log("Trying model source: %s" % base_url)
            try:
                for name in MODEL_FILES:
                    url = "%s/%s?download=true" % (base_url, quote(name))
                    _download_file(url, os.path.join(temp_dir, name), log)
                if _is_valid_omnilingual_dir(temp_dir):
                    if os.path.isdir(target_dir):
                        shutil.rmtree(target_dir)
                    os.replace(temp_dir, target_dir)
                    log("Model ready: %s" % target_dir)
                    return {"success": True, "model_dir": target_dir, "downloaded": True, "logs": logs}
            except Exception as exc:
                errors.append("%s -> %s" % (base_url, exc))
                log("Source failed: %s" % exc)
                for name in MODEL_FILES:
                    path = os.path.join(temp_dir, name)
                    if os.path.exists(path):
                        os.unlink(path)
        raise RuntimeError("Model download failed. " + " | ".join(errors))
    finally:
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
