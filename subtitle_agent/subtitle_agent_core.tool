#!/usr/bin/env python3

import argparse
import contextlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

RESOLVE_SCRIPT_API = os.environ.get("RESOLVE_SCRIPT_API")
if RESOLVE_SCRIPT_API:
    sys.path.insert(0, os.path.join(RESOLVE_SCRIPT_API, "Modules"))
else:
    sys.path.insert(
        0,
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    )


def _resolve_script_dir():
    candidates = []
    if "__file__" in globals() and __file__:
        candidates.append(__file__)
    if getattr(sys, "argv", None) and sys.argv and sys.argv[0]:
        candidates.append(sys.argv[0])
    main_mod = sys.modules.get("__main__")
    if main_mod is not None:
        main_file = getattr(main_mod, "__file__", None)
        if main_file:
            candidates.append(main_file)
    for candidate in candidates:
        try:
            abs_path = os.path.abspath(candidate)
            if os.path.exists(abs_path):
                return os.path.dirname(abs_path)
        except Exception:
            pass
    return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"


SCRIPT_DIR = _resolve_script_dir()
CONFIG_PATH = os.environ.get("SUBTITLE_AGENT_CONFIG_PATH") or os.path.join(SCRIPT_DIR, "subtitle_agent_config.json")

REGION_URLS = {
    "cn": "https://dashscope.aliyuncs.com/api/v1",
    "intl": "https://dashscope-intl.aliyuncs.com/api/v1",
}

DEFAULT_PROOFREAD_PROMPT = (
    "请作为专业影视字幕校对编辑，阅读整份 SRT 并输出一个用于全局文本替换的 JSON 词典。"
    "你的任务是找出需要修正的错别字、ASR 误识别、术语错误、英文大小写/拼写错误、中英空格问题和明显不自然的短语，"
    "将错误文本映射到正确文本。只输出 JSON，不要解释，不要输出 markdown。"
    "输出格式固定为 {\"replacements\":{\"错误文本\":\"正确文本\"}}。"
    "不要输出行号、序号、时码，不要重写整条字幕。"
    "尽量输出最小但安全的替换单元，避免过短到误伤其他字幕。"
    "如果无需修改，输出 {\"replacements\":{}}。"
)
DEFAULT_TRANSLATE_PROMPT = (
    "请将每条字幕翻译为目标语言 {target_lang}。要求：自然口语、影视字幕风格、简洁易读；"
    "保留人物称呼、专有名词和上下文语气；不要解释，不要改变序号和时码。"
)
DEFAULT_OPTIMIZE_PROMPT = (
    "请优化参考文案，使其更适合字幕强制对齐：修正错别字、明显标点问题、多余空白和不利于对齐的断行，"
    "如果单行文本过长，使用逗号拆分为两句，专有英语名词首字母大写，以及修正其他英文大小写错误；"
    "保留原始语义、顺序、人物称呼和专有名词。只输出优化后的纯文本，不要解释。"
)
SHORT_SUBTITLE_GAP_MS = 800

SRT_TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})")
HTML_TAG_RE = re.compile(r"<[^>]+>")
ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")


def load_json(path, default=None):
    if not os.path.isfile(path):
        return {} if default is None else default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _worker_log(logs, message):
    logs.append(message)
    print(message, file=sys.stderr, flush=True)


def load_agent_config():
    return load_json(CONFIG_PATH, {})


def sanitize_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or "subtitle_agent"


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)
    return path


def _get_resolve():
    import DaVinciResolveScript as dvr

    return dvr.scriptapp("Resolve")


def _require_resolve():
    resolve = _get_resolve()
    if not resolve:
        raise RuntimeError("DaVinci Resolve is not running or scripting is disabled")
    return resolve


def _require_project(resolve=None):
    resolve = resolve or _require_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No project is currently open")
    return project


def _require_timeline(project=None):
    project = project or _require_project()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No timeline is currently active")
    return timeline


def get_resolve_context():
    resolve = _require_resolve()
    project = _require_project(resolve)
    timeline = _require_timeline(project)
    version = {
        "product": resolve.GetProductName(),
        "version_string": resolve.GetVersionString(),
        "version": resolve.GetVersion(),
    }
    timelines = list_timelines(project)
    context = {
        "version": version,
        "project_name": project.GetName(),
        "project_name_safe": sanitize_name(project.GetName()),
        "current_timeline": timeline.GetName(),
        "start_timecode": timeline.GetStartTimecode(),
        "timelines": timelines,
    }
    if not context["start_timecode"].startswith("00"):
        context["warning"] = (
            "Timeline start timecode is not 00:00:00:00. SRT timing may be misaligned outside Resolve."
        )
    return context


def list_timelines(project=None):
    project = project or _require_project()
    count = project.GetTimelineCount()
    timelines = []
    for index in range(1, count + 1):
        timeline = project.GetTimelineByIndex(index)
        if timeline:
            timelines.append(
                {
                    "index": index,
                    "name": timeline.GetName(),
                    "start_frame": timeline.GetStartFrame(),
                    "end_frame": timeline.GetEndFrame(),
                    "start_timecode": timeline.GetStartTimecode(),
                }
            )
    return timelines


def set_current_timeline(index):
    project = _require_project()
    timeline = project.GetTimelineByIndex(int(index))
    if not timeline:
        raise RuntimeError("Timeline index %s not found" % index)
    if not project.SetCurrentTimeline(timeline):
        raise RuntimeError("Failed to switch timeline")
    return {
        "index": int(index),
        "name": timeline.GetName(),
        "start_timecode": timeline.GetStartTimecode(),
    }


def fix_timecode():
    timeline = _require_timeline()
    old_tc = timeline.GetStartTimecode()
    result = timeline.SetStartTimecode("00:00:00:00")
    new_tc = timeline.GetStartTimecode()
    if not result or new_tc != "00:00:00:00":
        raise RuntimeError("Failed to set start timecode (was %s)" % old_tc)
    return {"success": True, "old_timecode": old_tc, "new_timecode": new_tc}


def _frames_to_srt_tc(frames, fps):
    total_secs = frames / fps
    hours = int(total_secs // 3600)
    minutes = int((total_secs % 3600) // 60)
    seconds = int(total_secs % 60)
    millis = int(round((total_secs - int(total_secs)) * 1000))
    if millis >= 1000:
        seconds += 1
        millis = 0
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


def parse_srt_content(srt_content):
    blocks = re.split(r"\n\s*\n+", srt_content.strip()) if srt_content.strip() else []
    subtitles = []
    for block in blocks:
        lines = [line.rstrip("\r") for line in block.splitlines() if line.strip() != ""]
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0])
        except ValueError:
            continue
        match = SRT_TIME_RE.match(lines[1])
        if not match:
            continue
        subtitles.append(
            {
                "index": index,
                "start": match.group(1),
                "end": match.group(2),
                "text": "\n".join(lines[2:]),
            }
        )
    return subtitles


def read_srt_file(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        content = handle.read()
    items = parse_srt_content(content)
    return {"success": True, "path": path, "count": len(items), "items": items, "content": content}


def _plain_subtitle_text(text):
    text = str(text or "")
    text = text.replace("\\N", "\n")
    text = ASS_OVERRIDE_RE.sub("", text)
    text = HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


def export_subtitles_srt(output_path):
    timeline = _require_timeline()
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    if not items:
        raise RuntimeError("No subtitle items found on the timeline")
    project = _require_project()
    fps_str = project.GetSetting("timelineFrameRate")
    fps = float(fps_str) if fps_str else 24.0
    entries = []
    for idx, item in enumerate(items, 1):
        entries.append(
            {
                "index": idx,
                "start": _frames_to_srt_tc(item.GetStart(), fps),
                "end": _frames_to_srt_tc(item.GetEnd(), fps),
                "text": _plain_subtitle_text(item.GetName()),
            }
        )
    output_path = os.path.abspath(output_path)
    ensure_dir(os.path.dirname(output_path) or ".")
    _write_srt_entries(output_path, entries)
    return read_srt_file(output_path)


def _delete_all_subtitle_tracks(timeline):
    count = timeline.GetTrackCount("subtitle")
    while count > 0:
        timeline.DeleteTrack("subtitle", count)
        count = timeline.GetTrackCount("subtitle")


def generate_subtitles(chars_per_line=24):
    resolve = _require_resolve()
    project = _require_project(resolve)
    timeline = _require_timeline(project)
    _delete_all_subtitle_tracks(timeline)
    timeline.AddTrack("subtitle")
    settings = {resolve.SUBTITLE_CHARS_PER_LINE: int(chars_per_line)}
    result = timeline.CreateSubtitlesFromAudio(settings)
    if not result:
        raise RuntimeError("Failed to generate subtitles from audio")
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    return {
        "success": True,
        "count": len(items),
        "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items],
    }


def _find_rendered_file(target_dir, base_name, extensions=None, since=None):
    if not os.path.isdir(target_dir):
        return None
    matches = []
    wanted = set(ext.lower() for ext in extensions) if extensions else None
    for name in os.listdir(target_dir):
        if not name.startswith(base_name):
            continue
        path = os.path.join(target_dir, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if wanted is not None and ext not in wanted:
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        if since is not None and mtime + 2 < since:
            continue
        matches.append((mtime, path))
    if not matches:
        return None
    return sorted(matches)[-1][1]


def _ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("ffmpeg not found. Install ffmpeg or add it to PATH")


def _convert_to_wav(input_path, output_path):
    ensure_dir(os.path.dirname(os.path.abspath(output_path)) or ".")
    cmd = [
        _ffmpeg_exe(),
        "-y",
        "-i",
        input_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "48000",
        output_path,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("ffmpeg WAV conversion failed: %s" % (result.stderr or "")[-800:])
    if not os.path.isfile(output_path):
        raise RuntimeError("ffmpeg completed but WAV output was not found: %s" % output_path)
    return output_path


def _start_render_and_wait(project):
    render_fn = getattr(project, "Render", None)
    if callable(render_fn):
        result = render_fn()
        if not result:
            raise RuntimeError("Failed to start render job")
    else:
        add_job = getattr(project, "AddRenderJob", None)
        start_rendering = getattr(project, "StartRendering", None)
        if not callable(add_job) or not callable(start_rendering):
            raise RuntimeError("No callable render API found on Resolve project")
        job_id = add_job()
        if not job_id:
            raise RuntimeError("Failed to add render job")
        try:
            started = start_rendering(job_id)
        except TypeError:
            started = start_rendering([job_id])
        if not started:
            raise RuntimeError("Failed to start render job: %s" % job_id)

    is_rendering = getattr(project, "IsRenderingInProgress", None)
    if callable(is_rendering):
        while is_rendering():
            time.sleep(1)


def export_audio(output_path):
    resolve = _require_resolve()
    project = _require_project(resolve)
    _require_timeline(project)

    output_path = os.path.abspath(output_path)
    target_dir = os.path.dirname(output_path)
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    ensure_dir(target_dir)

    old_page = None
    try:
        old_page = resolve.GetCurrentPage()
        resolve.OpenPage("deliver")
    except Exception:
        old_page = None

    old_format = None
    try:
        fmt = project.GetCurrentRenderFormatAndCodec()
        if fmt:
            old_format = (fmt.get("format"), fmt.get("codec"))
    except Exception:
        old_format = None

    project.DeleteAllRenderJobs()
    render_started_at = time.time()

    base_settings = {
        "ExportVideo": False,
        "ExportAudio": True,
        "TargetDir": target_dir,
        "CustomName": base_name,
        "AudioBitDepth": 16,
        "AudioSampleRate": 48000,
        "SelectAllFrames": True,
    }
    attempts = []

    def remember(label, ok, error=None):
        attempts.append({"label": label, "ok": bool(ok), "error": str(error or "")})

    def try_render_with_current_format(format_name, codec_name, audio_codec):
        label = "SetCurrentRenderFormatAndCodec(%r, %r), AudioCodec=%r" % (
            format_name,
            codec_name,
            audio_codec,
        )
        try:
            if not project.SetCurrentRenderFormatAndCodec(format_name, codec_name):
                remember(label, False)
                return False
            settings = dict(base_settings)
            if audio_codec is not None:
                settings["AudioCodec"] = audio_codec
            if not project.SetRenderSettings(settings):
                remember(label + " SetRenderSettings", False)
                return False
            remember(label, True)
            return True
        except Exception as exc:
            remember(label, False, exc)
            return False

    def try_render_settings_only(format_name, audio_codec):
        label = "SetRenderSettings Format=%r, AudioCodec=%r" % (format_name, audio_codec)
        try:
            settings = dict(base_settings)
            settings["Format"] = format_name
            settings["AudioCodec"] = audio_codec
            ok = project.SetRenderSettings(settings)
            remember(label, ok)
            return bool(ok)
        except Exception as exc:
            remember(label, False, exc)
            return False

    def try_audio_only_preset(preset_name):
        label = "LoadRenderPreset(%r)" % preset_name
        try:
            if not project.LoadRenderPreset(preset_name):
                remember(label, False)
                return False
            settings = dict(base_settings)
            if project.SetRenderSettings(settings):
                remember(label, True)
                return True
            minimal_settings = {
                "TargetDir": target_dir,
                "CustomName": base_name,
                "SelectAllFrames": True,
            }
            ok = project.SetRenderSettings(minimal_settings)
            remember(label + " minimal SetRenderSettings", ok)
            return bool(ok)
        except Exception as exc:
            remember(label, False, exc)
            return False

    configured = False
    preset_attempts = [
        "Audio Only",
        "Audio Only - Wave",
        "Audio Only (WAV)",
        "WAV",
        "Wave",
    ]
    for preset_name in preset_attempts:
        if try_audio_only_preset(preset_name):
            configured = True
            break

    current_attempts = [
        ("wav", "pcm_s16le", "pcm_s16le"),
        ("Wave", "Linear PCM", "Linear PCM"),
        ("Wave", "LinearPCM", "LinearPCM"),
        ("wav", "LinearPCM", "LinearPCM"),
        ("wav", "Linear PCM", "Linear PCM"),
        ("wav", "", "LinearPCM"),
    ]
    if not configured:
        for format_name, codec_name, audio_codec in current_attempts:
            if try_render_with_current_format(format_name, codec_name, audio_codec):
                configured = True
                break

    if not configured:
        settings_attempts = [
            ("wav", "LinearPCM"),
            ("wav", "Linear PCM"),
            ("Wave", "LinearPCM"),
            ("Wave", "Linear PCM"),
            ("wav", "pcm_s16le"),
        ]
        for format_name, audio_codec in settings_attempts:
            if try_render_settings_only(format_name, audio_codec):
                configured = True
                break

    if not configured:
        diagnostics = {}
        try:
            diagnostics["formats"] = project.GetRenderFormats()
        except Exception as exc:
            diagnostics["formats_error"] = str(exc)
        for key in ("wav", "Wave"):
            try:
                diagnostics["codecs_%s" % key] = project.GetRenderCodecs(key)
            except Exception as exc:
                diagnostics["codecs_%s_error" % key] = str(exc)
        try:
            diagnostics["presets"] = project.GetRenderPresets()
        except Exception as exc:
            diagnostics["presets_error"] = str(exc)
        if old_format:
            try:
                project.SetCurrentRenderFormatAndCodec(old_format[0], old_format[1])
            except Exception:
                pass
        if old_page:
            try:
                resolve.OpenPage(old_page)
            except Exception:
                pass
        raise RuntimeError(
            "Failed to configure WAV audio export. Attempts: %s. Diagnostics: %s"
            % (json.dumps(attempts, ensure_ascii=False), json.dumps(diagnostics, ensure_ascii=False))
        )

    try:
        _start_render_and_wait(project)
    finally:
        if old_format:
            try:
                project.SetCurrentRenderFormatAndCodec(old_format[0], old_format[1])
            except Exception:
                pass
        if old_page:
            try:
                resolve.OpenPage(old_page)
            except Exception:
                pass

    source_path = None
    if os.path.isfile(output_path):
        try:
            if os.path.getmtime(output_path) + 2 >= render_started_at:
                source_path = output_path
        except Exception:
            source_path = output_path
    if source_path is None:
        source_path = _find_rendered_file(target_dir, base_name, [".wav"], render_started_at)
    converted = False
    if source_path is None:
        source_path = _find_rendered_file(
            target_dir,
            base_name,
            [".mp4", ".m4a", ".mov", ".aac", ".aif", ".aiff"],
            render_started_at,
        )
    if source_path and os.path.splitext(source_path)[1].lower() != ".wav":
        _convert_to_wav(source_path, output_path)
        converted = True
        source_path = output_path
    elif source_path and source_path != output_path:
        output_path = source_path

    if not os.path.isfile(output_path):
        raise RuntimeError("Audio export completed but output file was not found")

    return {
        "success": True,
        "path": output_path,
        "source_path": source_path,
        "converted": converted,
        "attempts": attempts,
    }


def run_export_audio(job):
    output_path = os.path.abspath(job["output"])
    result = export_audio(output_path)
    logs = []
    _worker_log(logs, "Audio exported by external Resolve scripting worker: %s" % result["path"])
    if result.get("converted"):
        _worker_log(logs, "Resolve rendered an AAC/MP4-style audio file; ffmpeg converted it to WAV.")
    result["logs"] = logs
    result["logs_streamed"] = True
    return result


def _make_resolve_import_copy(path, suffix=".srt"):
    source_path = os.path.abspath(path)
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    safe_base = _safe_name(base_name)
    fd, temp_path = tempfile.mkstemp(prefix="subtitle_agent_import_%s_" % safe_base, suffix=suffix)
    os.close(fd)
    shutil.copyfile(source_path, temp_path)
    return temp_path


def import_srt(path):
    source_path = os.path.abspath(path)
    if not os.path.isfile(source_path):
        raise RuntimeError("SRT file does not exist: %s" % source_path)
    resolve = _require_resolve()
    project = _require_project(resolve)
    media_pool = project.GetMediaPool()
    timeline = _require_timeline(project)
    root = media_pool.GetRootFolder()

    for clip in list(root.GetClipList() or []):
        if clip.GetName().lower().endswith(".srt"):
            media_pool.DeleteClips([clip])

    _delete_all_subtitle_tracks(timeline)

    import_copy_path = _make_resolve_import_copy(source_path, suffix=".srt")
    try:
        imported = media_pool.ImportMedia([import_copy_path])
        if not imported:
            raise RuntimeError("Failed to import SRT file into Media Pool")
        subtitle_clip = imported[0]
        timeline.AddTrack("subtitle")
        result = media_pool.AppendToTimeline([subtitle_clip])
        if not result:
            raise RuntimeError("Failed to append subtitles to timeline")
        items = timeline.GetItemListInTrack("subtitle", 1) or []
        return {
            "success": True,
            "path": source_path,
            "import_path": import_copy_path,
            "count": len(items),
            "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items],
        }
    finally:
        try:
            os.remove(import_copy_path)
        except OSError:
            pass


def _temp_json(prefix, payload):
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json")
    os.close(fd)
    write_json(path, payload)
    return path


def _ms_to_srt(ms):
    hours = int(ms // 3600000)
    minutes = int((ms % 3600000) // 60000)
    seconds = int((ms % 60000) // 1000)
    millis = int(ms % 1000)
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


def _srt_to_ms(value):
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", str(value or "").strip())
    if not match:
        raise RuntimeError("Invalid SRT timecode: %s" % value)
    hours, minutes, seconds, millis = [int(part) for part in match.groups()]
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _collapse_short_gaps(entries, min_gap_ms=SHORT_SUBTITLE_GAP_MS):
    if not entries:
        return []
    normalized = [
        {
            "index": entry["index"],
            "start": entry["start"],
            "end": entry["end"],
            "text": entry["text"],
        }
        for entry in entries
    ]
    for index in range(len(normalized) - 1):
        current = normalized[index]
        following = normalized[index + 1]
        current_end_ms = _srt_to_ms(current["end"])
        next_start_ms = _srt_to_ms(following["start"])
        gap_ms = next_start_ms - current_end_ms
        if 0 < gap_ms < int(min_gap_ms):
            midpoint_ms = current_end_ms + (gap_ms // 2)
            midpoint_tc = _ms_to_srt(midpoint_ms)
            current["end"] = midpoint_tc
            following["start"] = midpoint_tc
    return normalized


def _init_dashscope(config):
    import dashscope

    api_key = (config.get("api_key") or os.environ.get("DASHSCOPE_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("DashScope API key is missing")
    dashscope.api_key = api_key
    region = (config.get("region") or "cn").strip()
    dashscope.base_http_api_url = REGION_URLS.get(region, REGION_URLS["cn"])
    return dashscope


def _upload_audio(audio_path, logs):
    from dashscope import Files

    _worker_log(logs, "Uploading audio: %s" % os.path.basename(audio_path))
    response = Files.upload(file_path=audio_path, purpose="file_asr")
    file_id = response.get("output", {}).get("uploaded_files", [{}])[0].get("file_id", "")
    if not file_id:
        raise RuntimeError("Upload succeeded but file_id was missing")
    for _ in range(5):
        time.sleep(1)
        file_info = Files.get(file_id)
        if file_info:
            break
    else:
        raise RuntimeError("Uploaded file metadata was not ready")
    file_url = file_info.get("output", {}).get("url", "")
    if not file_url:
        raise RuntimeError("Failed to fetch uploaded file URL")
    return file_url


def _transcribe_remote(file_url, language, config, logs):
    from dashscope.audio.asr import Transcription

    model = (config.get("model") or "").strip() or "fun-asr"
    max_retries = int(config.get("transcription_max_retries", 600))
    poll_interval = int(config.get("transcription_poll_interval", 2))
    _worker_log(logs, "Submitting DashScope transcription (%s / %s)" % (model, language))
    task_response = Transcription.async_call(
        model=model,
        file_urls=[file_url],
        language_hints=[language],
    )
    task_id = getattr(task_response, "output", {}).get("task_id", None)
    if not task_id:
        raise RuntimeError("DashScope transcription submission failed")
    for attempt in range(max_retries):
        time.sleep(poll_interval)
        result = Transcription.wait(task=task_id)
        status = getattr(result, "output", {}).get("task_status", "UNKNOWN")
        if status == "SUCCEEDED":
            _worker_log(logs, "Remote transcription finished")
            return result
        if status == "FAILED":
            message = getattr(result, "output", {}).get("message", "unknown error")
            raise RuntimeError("Remote transcription failed: %s" % message)
        if attempt and attempt % max(1, 15 // max(poll_interval, 1)) == 0:
            _worker_log(logs, "Waiting for remote transcription...")
    raise RuntimeError("Remote transcription timed out")


def _result_to_srt(transcription_result, max_words=0):
    import requests

    output = transcription_result.get("output", {}) if isinstance(transcription_result, dict) else {}
    task_results = output.get("results", [])
    all_words = []
    for item in task_results:
        transcription_url = item.get("transcription_url", "")
        if not transcription_url:
            continue
        response = requests.get(transcription_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        for transcript in data.get("transcripts", []):
            for sentence in transcript.get("sentences", []):
                words = sentence.get("words", [])
                if not words:
                    all_words.append(
                        {
                            "begin_time": int(sentence.get("begin_time", 0)),
                            "end_time": int(sentence.get("end_time", 0)),
                            "text": sentence.get("text", "").strip(),
                            "punct": "",
                        }
                    )
                    continue
                for word in words:
                    all_words.append(
                        {
                            "begin_time": int(word.get("begin_time", 0)),
                            "end_time": int(word.get("end_time", 0)),
                            "text": word.get("text", "").strip(),
                            "punct": word.get("punctuation", ""),
                        }
                    )

    if not all_words:
        return "\n", 0

    lines = []
    punct_set = set("。！？，；：")
    buffer_text = ""
    buffer_start = 0
    buffer_end = 0
    buffer_len = 0

    def flush():
        nonlocal buffer_text, buffer_start, buffer_end, buffer_len
        text = buffer_text.strip().rstrip("，。！？；：、")
        if text:
            lines.append(str(len(lines) // 4 + 1))
            lines.append("%s --> %s" % (_ms_to_srt(buffer_start), _ms_to_srt(buffer_end)))
            lines.append(text)
            lines.append("")
        buffer_text = ""
        buffer_start = 0
        buffer_end = 0
        buffer_len = 0

    for word in all_words:
        punct = word.get("punct", "")
        if buffer_len == 0:
            buffer_start = word["begin_time"]
        buffer_text += word["text"] + punct
        buffer_end = word["end_time"]
        buffer_len += 1
        if punct and punct[-1] in punct_set:
            flush()
        elif max_words > 0 and buffer_len >= max_words:
            flush()
    flush()
    return "\n".join(lines), len(lines) // 4


def run_asr(job):
    config = {
        "api_key": job.get("dashscope_api_key", ""),
        "region": job.get("region", "cn"),
        "model": job.get("model", ""),
        "transcription_max_retries": job.get("transcription_max_retries", 600),
        "transcription_poll_interval": job.get("transcription_poll_interval", 2),
    }
    logs = []
    audio_path = os.path.abspath(job["audio"])
    output_path = os.path.abspath(job["output"])
    language = job.get("lang", "zh")
    max_words = int(job.get("max_words", 0))
    _worker_log(logs, "Running remote ASR")
    _init_dashscope(config)
    file_url = _upload_audio(audio_path, logs)
    result = _transcribe_remote(file_url, language, config, logs)
    srt_text, count = _result_to_srt(result, max_words=max_words)
    _write_srt_entries(output_path, parse_srt_content(srt_text))
    srt_data = read_srt_file(output_path)
    return {
        "success": True,
        "path": output_path,
        "count": len(srt_data["items"]),
        "items": srt_data["items"],
        "logs": logs,
        "logs_streamed": True,
    }


def _read_srt_entries(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        lines = handle.readlines()

    entries = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        try:
            seq = int(line)
        except ValueError:
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        match = SRT_TIME_RE.match(lines[index + 1].strip())
        if not match:
            index += 1
            continue
        start, end = match.groups()
        index += 2
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].rstrip("\r\n"))
            index += 1
        entries.append({"index": seq, "start": start, "end": end, "text": "\n".join(text_lines)})
        index += 1
    return entries


def _write_srt_entries(path, entries):
    entries = _collapse_short_gaps(entries)
    lines = []
    for entry in entries:
        lines.append(str(entry["index"]))
        lines.append("%s --> %s" % (entry["start"], entry["end"]))
        lines.append(entry["text"])
        lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def _load_corrections(path):
    if not path:
        return {}
    data = load_json(path, {})
    if not isinstance(data, dict):
        raise RuntimeError("Corrections file must be a JSON object")
    return data


def _apply_corrections_to_text(text, corrections):
    for wrong, correct in corrections.items():
        text = text.replace(wrong, correct)
    return text


def _zhconv_convert(text, lang):
    try:
        from zhconv import convert as zh_convert
    except ImportError:
        return text
    target = {
        "zh_cn": "zh-cn",
        "zh-cn": "zh-cn",
        "zh_tw": "zh-tw",
        "zh-tw": "zh-tw",
        "zh_hk": "zh-hk",
        "zh-hk": "zh-hk",
    }.get(lang.lower(), "zh-cn")
    return zh_convert(text, target)


def _fix_cjk_spacing(text):
    text = re.sub(r"([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])\s+([a-zA-Z0-9])", r"\1\2", text)
    text = re.sub(r"([a-zA-Z0-9])\s+([\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef])", r"\1\2", text)
    return text


def _fix_punctuation(text):
    text = re.sub(r"，,", "，", text)
    text = re.sub(r",，", "，", text)
    text = re.sub(r"[.][.]+", "…", text)
    text = re.sub(r"…\.", "…", text)
    text = re.sub(r"۔\.", "。", text)
    return text.replace('"', "「")


def run_read_srt(job):
    result = read_srt_file(os.path.abspath(job["path"]))
    result["logs"] = ["Loaded SRT: %s" % result["path"]]
    return result


def run_convert_srt(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    lang = job.get("lang", "zh-cn")
    corrections = _load_corrections(job.get("corrections"))
    entries = _read_srt_entries(input_path)
    logs = ["Converting SRT to %s" % lang]
    changed_count = 0
    original_count = len(entries)
    for entry in entries:
        before = entry["text"]
        text = before
        if corrections:
            text = _apply_corrections_to_text(text, corrections)
        if lang:
            text = _zhconv_convert(text, lang)
        text = _fix_cjk_spacing(text)
        text = _fix_punctuation(text)
        entry["text"] = text
        if text != before:
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update(
        {
            "original_count": original_count,
            "changed_count": changed_count,
            "logs": logs,
        }
    )
    return result


def run_apply_corrections(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    corrections = _load_corrections(job.get("corrections"))
    entries = _read_srt_entries(input_path)
    changed_count = 0
    for entry in entries:
        before = entry["text"]
        entry["text"] = _apply_corrections_to_text(entry["text"], corrections)
        if entry["text"] != before:
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count, "logs": ["Applied text replacements"]})
    return result


def _stream_event(event_type, **payload):
    payload["type"] = event_type
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _safe_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "").strip("_") or "subtitle_agent"


def _format_exception_details(exc, max_depth=3):
    parts = []
    current = exc
    depth = 0
    while current is not None and depth < max_depth:
        text = str(current).strip()
        label = type(current).__name__
        parts.append("%s: %s" % (label, text) if text else label)
        current = current.__cause__ or current.__context__
        depth += 1
    return " | ".join(parts)


def _require_llm_config(job):
    api_key = job.get("api_key") or os.environ.get("DASHSCOPE_API_KEY") or ""
    if not api_key:
        raise RuntimeError("dashscope_api_key is required for LLM features")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai is not installed. Run: pip install openai")
    return {
        "client": OpenAI(
            api_key=api_key,
            base_url=job.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=float(job.get("timeout_seconds") or 180),
            max_retries=int(job.get("connection_retries") or 3),
        ),
        "base_url": job.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": job.get("model") or "deepseek-v4-flash",
        "enable_thinking": bool(job.get("enable_thinking", True)),
        "timeout_seconds": float(job.get("timeout_seconds") or 180),
        "connection_retries": max(1, int(job.get("connection_retries") or 3)),
    }


def _extract_json_object(text):
    text = (text or "").strip()
    if not text:
        raise RuntimeError("LLM response was empty")

    candidates = [text]
    fence_matches = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    for match in fence_matches:
        match = (match or "").strip()
        if match:
            candidates.insert(0, match)

    decoder = json.JSONDecoder()
    parse_errors = []

    for candidate in candidates:
        for match in re.finditer(r"\{", candidate):
            start = match.start()
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
                if isinstance(parsed, dict):
                    return parsed
            except Exception as exc:
                parse_errors.append(str(exc))

        in_string = False
        escaped = False
        depth = 0
        start = None
        for index, char in enumerate(candidate):
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                if depth == 0:
                    start = index
                depth += 1
            elif char == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        snippet = candidate[start : index + 1]
                        try:
                            parsed = json.loads(snippet)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception as exc:
                            parse_errors.append(str(exc))
                        start = None

    detail = parse_errors[-1] if parse_errors else "no JSON object found"
    preview = text[:400].replace("\n", "\\n")
    raise RuntimeError("Failed to parse LLM JSON object: %s. Preview: %s" % (detail, preview))


def _validate_llm_srt_json(data):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise RuntimeError("LLM JSON must be an object with an items list")
    normalized = []
    for item in data["items"]:
        if not isinstance(item, dict):
            continue
        if "index" not in item or "text" not in item:
            continue
        normalized.append({"index": int(item["index"]), "text": str(item["text"])})
    return {"items": normalized}


def _validate_llm_replacements_json(data):
    if not isinstance(data, dict):
        raise RuntimeError("LLM proofread JSON must be an object with a replacements mapping")
    replacements = data.get("replacements")
    if not isinstance(replacements, dict):
        raise RuntimeError("LLM proofread JSON must contain a replacements object")
    normalized = []
    for wrong, correct in replacements.items():
        wrong_text = str(wrong or "").strip()
        correct_text = str(correct or "").strip()
        if not wrong_text or wrong_text == correct_text:
            continue
        normalized.append((wrong_text, correct_text))
    return {"replacements": dict(normalized)}


def _normalized_replacement_items(replacements):
    normalized = []
    for wrong, correct in (replacements or {}).items():
        wrong_text = str(wrong or "").strip()
        correct_text = str(correct or "").strip()
        if not wrong_text or wrong_text == correct_text:
            continue
        normalized.append((wrong_text, correct_text))
    normalized.sort(key=lambda item: len(item[0]), reverse=True)
    return normalized


def _apply_index_text_edits(input_path, output_path, edit_json):
    entries = _read_srt_entries(input_path)
    edits = {int(item["index"]): item["text"] for item in edit_json.get("items", [])}
    changed_count = 0
    for entry in entries:
        index = int(entry["index"])
        if index in edits and entry["text"] != edits[index]:
            entry["text"] = edits[index]
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count})
    return result


def _apply_replacements_to_srt(input_path, output_path, replacements_json):
    entries = _read_srt_entries(input_path)
    replacements = _normalized_replacement_items(replacements_json.get("replacements") or {})
    changed_count = 0
    for entry in entries:
        original_text = entry["text"]
        updated_text = original_text
        placeholders = []
        for index, (wrong, correct) in enumerate(replacements):
            placeholder = "__SUBTITLE_AGENT_REPL_%s__" % index
            if wrong in updated_text:
                updated_text = updated_text.replace(wrong, placeholder)
                placeholders.append((placeholder, correct))
        for placeholder, correct in placeholders:
            updated_text = updated_text.replace(placeholder, correct)
        if updated_text != original_text:
            entry["text"] = updated_text
            changed_count += 1
    _write_srt_entries(output_path, entries)
    result = read_srt_file(output_path)
    result.update({"changed_count": changed_count, "replacement_count": len(replacements)})
    return result


def _llm_stream_chat(job, messages):
    config = _require_llm_config(job)
    _stream_event("status", message="连接 LLM：%s" % config["model"])
    _stream_event(
        "status",
        message="LLM endpoint：%s，timeout=%ss" % (config["base_url"], int(config["timeout_seconds"])),
    )
    try:
        import httpx
    except Exception:
        httpx = None
    try:
        from openai import APIConnectionError, APITimeoutError
        retryable = [APIConnectionError, APITimeoutError]
    except Exception:
        retryable = []
    if httpx is not None:
        retryable.extend([httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout])
    retryable = tuple(retryable) if retryable else (Exception,)
    last_detail = ""
    for attempt in range(1, config["connection_retries"] + 1):
        try:
            stream = config["client"].chat.completions.create(
                model=config["model"],
                messages=messages,
                extra_body={"enable_thinking": config["enable_thinking"]},
                stream=True,
                stream_options={"include_usage": True},
            )
            answer_content = ""
            reasoning_length = 0
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        _stream_event("status", message="Token 消耗：%s" % usage)
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning:
                    reasoning_length += len(reasoning)
                    _stream_event("reasoning_summary", message="思维链文本长度：%s 字符" % reasoning_length)
                content = getattr(delta, "content", None)
                if content:
                    answer_content += content
                    _stream_event("content_delta", text=content)
            return answer_content
        except retryable as exc:
            last_detail = _format_exception_details(exc)
            if attempt < config["connection_retries"]:
                wait_seconds = min(5, 2 ** (attempt - 1))
                _stream_event(
                    "status",
                    message="LLM 连接异常，第 %s/%s 次重试前等待 %ss：%s"
                    % (attempt, config["connection_retries"], wait_seconds, last_detail),
                )
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(
                "LLM connection failed after %s attempts. endpoint=%s model=%s detail=%s"
                % (config["connection_retries"], config["base_url"], config["model"], last_detail)
            )
        except Exception as exc:
            detail = _format_exception_details(exc)
            raise RuntimeError(
                "LLM request failed. endpoint=%s model=%s detail=%s"
                % (config["base_url"], config["model"], detail)
            )
    raise RuntimeError(
        "LLM connection failed. endpoint=%s model=%s detail=%s"
        % (config["base_url"], config["model"], last_detail or "unknown error")
    )


def run_llm_srt_edit_stream(job):
    input_path = os.path.abspath(job["input"])
    output_path = os.path.abspath(job["output"])
    json_output = os.path.abspath(job["json_output"])
    mode = job.get("mode", "proofread")
    target_lang = job.get("target_lang", "zh-cn")
    srt_data = read_srt_file(input_path)
    mode_text = "翻译" if mode == "translate" else "校对"
    _stream_event("status", message="读取 SRT：%s（%s 条）" % (input_path, srt_data["count"]))
    if mode == "translate":
        instruction = (job.get("translate_prompt") or DEFAULT_TRANSLATE_PROMPT).replace("{target_lang}", target_lang)
        reference_section = ""
    else:
        instruction = job.get("proofread_prompt") or DEFAULT_PROOFREAD_PROMPT
        reference_text = (job.get("reference_text") or "").strip()
        reference_section = ""
        if reference_text:
            reference_section = (
                "\n\n参考文案如下。请将它作为校对依据，用来判断专有名词、英文大小写、"
                "术语、人物称呼、上下文语义和漏识别/误识别；但输出仍必须只针对 SRT 条目文本，"
                "不要新增、删除或移动字幕条目：\n%s"
                % reference_text
            )
    messages = [
        {
            "role": "system",
            "content": (
                "你是专业影视字幕编辑。"
                "当任务是校对时，必须只输出 JSON 对象，格式为 "
                "{\"replacements\":{\"错误文本\":\"正确文本\"}}。"
                "当任务是翻译时，必须只输出 JSON 对象，格式为 "
                "{\"items\":[{\"index\":1,\"text\":\"修改后的字幕文本\"}]}。"
                "不要输出 markdown 或解释。"
            ),
        },
        {
            "role": "user",
            "content": "%s%s\n\nSRT 内容如下：\n%s" % (instruction, reference_section, srt_data["content"]),
        },
    ]
    _stream_event("status", message="调用 LLM 生成%s JSON" % mode_text)
    answer = _llm_stream_chat(job, messages)
    _stream_event("status", message="解析 LLM JSON")
    if mode == "translate":
        edit_json = _validate_llm_srt_json(_extract_json_object(answer))
    else:
        edit_json = _validate_llm_replacements_json(_extract_json_object(answer))
    ensure_dir(os.path.dirname(json_output) or ".")
    write_json(json_output, edit_json)
    _stream_event("status", message="应用 JSON 到新 SRT")
    if mode == "translate":
        result = _apply_index_text_edits(input_path, output_path, edit_json)
    else:
        result = _apply_replacements_to_srt(input_path, output_path, edit_json)
    result.update(
        {
            "json_path": json_output,
            "logs": [
                "LLM %s JSON written to %s" % (mode_text, json_output),
                "LLM %s SRT written to %s" % (mode_text, output_path),
            ],
        }
    )
    _stream_event("result", payload=result)


def run_llm_optimize_text_stream(job):
    text = (job.get("text") or "").strip()
    if not text:
        raise RuntimeError("Reference text is empty")
    _stream_event("status", message="调用 LLM 优化参考文案")
    prompt = job.get("optimize_prompt") or DEFAULT_OPTIMIZE_PROMPT
    messages = [
        {
            "role": "system",
            "content": prompt,
        },
        {"role": "user", "content": text},
    ]
    optimized = _llm_stream_chat(job, messages).strip()
    _stream_event("result", payload={"success": True, "text": optimized, "logs": ["Reference text optimized by LLM"]})


def run_worker_job(job):
    action = job.get("action")
    if action == "export_audio":
        return run_export_audio(job)
    if action == "asr":
        return run_asr(job)
    if action == "read_srt":
        return run_read_srt(job)
    if action == "convert_srt":
        return run_convert_srt(job)
    if action == "apply_corrections":
        return run_apply_corrections(job)
    raise RuntimeError("Unknown worker action: %s" % action)


def _cli_worker(job_json_path):
    try:
        job = load_json(job_json_path, {})
        action = job.get("action")
        if action == "llm_srt_edit":
            run_llm_srt_edit_stream(job)
            return 0
        if action == "llm_optimize_text":
            run_llm_optimize_text_stream(job)
            return 0
        with contextlib.redirect_stdout(sys.stderr):
            result = run_worker_job(job)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        if "job" in locals() and job.get("action") in ("llm_srt_edit", "llm_optimize_text"):
            _stream_event("error", message=str(exc))
        else:
            print(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description="Subtitle Agent Core")
    subparsers = parser.add_subparsers(dest="command")
    worker_parser = subparsers.add_parser("worker", help="Run a worker job from JSON")
    worker_parser.add_argument("job_json")
    args = parser.parse_args()

    if args.command == "worker":
        return _cli_worker(args.job_json)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
