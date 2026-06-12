#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import tempfile
import time

from .bootstrap import ensure_dir, plain_subtitle_text, sanitize_name, worker_log
from .srt_ops import read_srt_file, write_srt_entries


def get_resolve():
    import DaVinciResolveScript as dvr

    return dvr.scriptapp("Resolve")


def require_resolve():
    resolve = get_resolve()
    if not resolve:
        raise RuntimeError("DaVinci Resolve is not running or scripting is disabled")
    return resolve


def require_project(resolve=None):
    resolve = resolve or require_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("No project is currently open")
    return project


def require_timeline(project=None):
    project = project or require_project()
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("No timeline is currently active")
    return timeline


def get_resolve_context():
    resolve = require_resolve()
    project = require_project(resolve)
    timeline = require_timeline(project)
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
        context["warning"] = "Timeline start timecode is not 00:00:00:00. SRT timing may be misaligned outside Resolve."
    return context


def list_timelines(project=None):
    project = project or require_project()
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
    project = require_project()
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
    timeline = require_timeline()
    old_tc = timeline.GetStartTimecode()
    result = timeline.SetStartTimecode("00:00:00:00")
    new_tc = timeline.GetStartTimecode()
    if not result or new_tc != "00:00:00:00":
        raise RuntimeError("Failed to set start timecode (was %s)" % old_tc)
    return {"success": True, "old_timecode": old_tc, "new_timecode": new_tc}


def frames_to_srt_tc(frames, fps):
    total_secs = frames / fps
    hours = int(total_secs // 3600)
    minutes = int((total_secs % 3600) // 60)
    seconds = int(total_secs % 60)
    millis = int(round((total_secs - int(total_secs)) * 1000))
    if millis >= 1000:
        seconds += 1
        millis = 0
    return "%02d:%02d:%02d,%03d" % (hours, minutes, seconds, millis)


def export_subtitles_srt(output_path):
    timeline = require_timeline()
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    if not items:
        raise RuntimeError("No subtitle items found on the timeline")
    project = require_project()
    fps_str = project.GetSetting("timelineFrameRate")
    fps = float(fps_str) if fps_str else 24.0
    entries = []
    for idx, item in enumerate(items, 1):
        entries.append(
            {
                "index": idx,
                "start": frames_to_srt_tc(item.GetStart(), fps),
                "end": frames_to_srt_tc(item.GetEnd(), fps),
                "text": plain_subtitle_text(item.GetName()),
            }
        )
    output_path = os.path.abspath(output_path)
    ensure_dir(os.path.dirname(output_path) or ".")
    write_srt_entries(output_path, entries)
    return read_srt_file(output_path)


def delete_all_subtitle_tracks(timeline):
    count = timeline.GetTrackCount("subtitle")
    while count > 0:
        timeline.DeleteTrack("subtitle", count)
        count = timeline.GetTrackCount("subtitle")


def generate_subtitles(chars_per_line=24):
    resolve = require_resolve()
    project = require_project(resolve)
    timeline = require_timeline(project)
    delete_all_subtitle_tracks(timeline)
    timeline.AddTrack("subtitle")
    settings = {resolve.SUBTITLE_CHARS_PER_LINE: int(chars_per_line)}
    result = timeline.CreateSubtitlesFromAudio(settings)
    if not result:
        raise RuntimeError("Failed to generate subtitles from audio")
    items = timeline.GetItemListInTrack("subtitle", 1) or []
    return {"success": True, "count": len(items), "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items]}


def find_rendered_file(target_dir, base_name, extensions=None, since=None):
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


def ffmpeg_exe():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("ffmpeg not found. Install ffmpeg or add it to PATH")


def convert_to_wav(input_path, output_path):
    ensure_dir(os.path.dirname(os.path.abspath(output_path)) or ".")
    cmd = [ffmpeg_exe(), "-y", "-i", input_path, "-vn", "-acodec", "pcm_s16le", "-ar", "48000", output_path]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, check=False)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg WAV conversion failed: %s" % (result.stderr or "")[-800:])
    if not os.path.isfile(output_path):
        raise RuntimeError("ffmpeg completed but WAV output was not found: %s" % output_path)
    return output_path


def start_render_and_wait(project):
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
    resolve = require_resolve()
    project = require_project(resolve)
    require_timeline(project)
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
        label = "SetCurrentRenderFormatAndCodec(%r, %r), AudioCodec=%r" % (format_name, codec_name, audio_codec)
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
            minimal_settings = {"TargetDir": target_dir, "CustomName": base_name, "SelectAllFrames": True}
            ok = project.SetRenderSettings(minimal_settings)
            remember(label + " minimal SetRenderSettings", ok)
            return bool(ok)
        except Exception as exc:
            remember(label, False, exc)
            return False

    configured = False
    for preset_name in ["Audio Only", "Audio Only - Wave", "Audio Only (WAV)", "WAV", "Wave"]:
        if try_audio_only_preset(preset_name):
            configured = True
            break
    if not configured:
        for format_name, codec_name, audio_codec in [
            ("wav", "pcm_s16le", "pcm_s16le"),
            ("Wave", "Linear PCM", "Linear PCM"),
            ("Wave", "LinearPCM", "LinearPCM"),
            ("wav", "LinearPCM", "LinearPCM"),
            ("wav", "Linear PCM", "Linear PCM"),
            ("wav", "", "LinearPCM"),
        ]:
            if try_render_with_current_format(format_name, codec_name, audio_codec):
                configured = True
                break
    if not configured:
        for format_name, audio_codec in [("wav", "LinearPCM"), ("wav", "Linear PCM"), ("Wave", "LinearPCM"), ("Wave", "Linear PCM"), ("wav", "pcm_s16le")]:
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
        raise RuntimeError("Failed to configure WAV audio export. Attempts: %s. Diagnostics: %s" % (json.dumps(attempts, ensure_ascii=False), json.dumps(diagnostics, ensure_ascii=False)))
    try:
        start_render_and_wait(project)
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
        source_path = find_rendered_file(target_dir, base_name, [".wav"], render_started_at)
    converted = False
    if source_path is None:
        source_path = find_rendered_file(target_dir, base_name, [".mp4", ".m4a", ".mov", ".aac", ".aif", ".aiff"], render_started_at)
    if source_path and os.path.splitext(source_path)[1].lower() != ".wav":
        convert_to_wav(source_path, output_path)
        converted = True
        source_path = output_path
    elif source_path and source_path != output_path:
        output_path = source_path
    if not os.path.isfile(output_path):
        raise RuntimeError("Audio export completed but output file was not found")
    return {"success": True, "path": output_path, "source_path": source_path, "converted": converted, "attempts": attempts}


def run_export_audio(job):
    output_path = os.path.abspath(job["output"])
    result = export_audio(output_path)
    logs = []
    worker_log(logs, "Audio exported by external Resolve scripting worker: %s" % result["path"])
    if result.get("converted"):
        worker_log(logs, "Resolve rendered an AAC/MP4-style audio file; ffmpeg converted it to WAV.")
    result["logs"] = logs
    result["logs_streamed"] = True
    return result


def make_resolve_import_copy(path, suffix=".srt"):
    source_path = os.path.abspath(path)
    base_name = os.path.splitext(os.path.basename(source_path))[0]
    safe_base = sanitize_name(base_name)
    fd, temp_path = tempfile.mkstemp(prefix="subtitle_agent_import_%s_" % safe_base, suffix=suffix)
    os.close(fd)
    shutil.copyfile(source_path, temp_path)
    return temp_path


def import_srt(path):
    source_path = os.path.abspath(path)
    if not os.path.isfile(source_path):
        raise RuntimeError("SRT file does not exist: %s" % source_path)
    resolve = require_resolve()
    project = require_project(resolve)
    media_pool = project.GetMediaPool()
    timeline = require_timeline(project)
    root = media_pool.GetRootFolder()
    for clip in list(root.GetClipList() or []):
        if clip.GetName().lower().endswith(".srt"):
            media_pool.DeleteClips([clip])
    delete_all_subtitle_tracks(timeline)
    import_copy_path = make_resolve_import_copy(source_path, suffix=".srt")
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
        return {"success": True, "path": source_path, "import_path": import_copy_path, "count": len(items), "items": [{"start": item.GetStart(), "end": item.GetEnd(), "text": item.GetName()} for item in items]}
    finally:
        try:
            os.remove(import_copy_path)
        except OSError:
            pass

