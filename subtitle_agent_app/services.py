import os


def read_text_file(path):
    with open(os.path.abspath(os.path.expanduser(path)), "r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


def preview_payload_to_text(payload):
    if isinstance(payload, dict):
        content = payload.get("content")
        if content is not None:
            return content
        items = payload.get("items", [])
    else:
        items = payload or []

    lines = []
    for index, entry in enumerate(items, 1):
        lines.append(str(entry.get("index") or index))
        lines.append("%s --> %s" % (entry.get("start", ""), entry.get("end", "")))
        lines.append(entry.get("text", ""))
        lines.append("")
    return "\n".join(lines)

