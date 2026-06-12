#!/usr/bin/env python3

import argparse
import contextlib
import json
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from subtitle_agent_app.core.asr_ops import run_asr
    from subtitle_agent_app.core.bootstrap import load_json
    from subtitle_agent_app.core.llm_ops import run_llm_optimize_text_stream, run_llm_srt_edit_stream, _stream_event
    from subtitle_agent_app.core.resolve_ops import run_export_audio
    from subtitle_agent_app.core.srt_ops import run_apply_corrections, run_convert_srt, run_read_srt
else:
    from .asr_ops import run_asr
    from .bootstrap import load_json
    from .llm_ops import _stream_event, run_llm_optimize_text_stream, run_llm_srt_edit_stream
    from .resolve_ops import run_export_audio
    from .srt_ops import run_apply_corrections, run_convert_srt, run_read_srt


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


def cli_worker(job_json_path):
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


def build_parser():
    parser = argparse.ArgumentParser(description="Subtitle Agent Core")
    subparsers = parser.add_subparsers(dest="command")
    worker_parser = subparsers.add_parser("worker", help="Run a worker job from JSON")
    worker_parser.add_argument("job_json")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "worker":
        return cli_worker(args.job_json)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

