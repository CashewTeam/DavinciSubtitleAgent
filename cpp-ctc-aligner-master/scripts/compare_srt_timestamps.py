#!/usr/bin/env python3
"""Compare SRT timestamps between two files with configurable tolerance."""
import re
import sys
import argparse

def parse_srt_time(time_str):
    """Parse SRT time format HH:MM:SS,mmm to seconds."""
    match = re.match(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})', time_str)
    if not match:
        return None
    h, m, s, ms = map(int, match.groups())
    return h * 3600 + m * 60 + s + ms / 1000

def parse_srt(filepath):
    """Parse SRT file, return list of (index, start, end, text)."""
    segments = []
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    blocks = re.split(r'\n\n+', content.strip())
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            idx = int(lines[0])
            times = lines[1].split(' --> ')
            start = parse_srt_time(times[0])
            end = parse_srt_time(times[1].split()[0])
            text = '\n'.join(lines[2:])
            segments.append((idx, start, end, text))
    return segments

def compare_srts(ref_path, test_path, tolerance_ms=20):
    """Compare two SRT files, return (pass, details)."""
    ref = parse_srt(ref_path)
    test = parse_srt(test_path)

    if len(ref) != len(test):
        return False, f"Segment count mismatch: ref={len(ref)}, test={len(test)}"

    tolerance_sec = tolerance_ms / 1000
    errors = []
    for i, (r, t) in enumerate(zip(ref, test)):
        start_diff = abs(r[1] - t[1])
        end_diff = abs(r[2] - t[2])
        if start_diff > tolerance_sec or end_diff > tolerance_sec:
            errors.append(f"Seg {i+1}: start_diff={start_diff*1000:.0f}ms, end_diff={end_diff*1000:.0f}ms")

    if errors:
        return False, '\n'.join(errors)
    return True, f"All {len(ref)} segments within {tolerance_ms}ms tolerance"

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('reference', help='Reference SRT file (Python output)')
    parser.add_argument('test', help='Test SRT file (C++ output)')
    parser.add_argument('--tolerance', type=int, default=20, help='Tolerance in ms (default: 20)')
    args = parser.parse_args()

    passed, msg = compare_srts(args.reference, args.test, args.tolerance)
    print(msg)
    sys.exit(0 if passed else 1)
