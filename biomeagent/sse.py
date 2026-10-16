"""Server-sent events for one chat turn. Same four names as ProtDAP: status, token, done, error."""

import json


def encode_sse(event, payload):
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def parse_sse(lines):
    event = "message"
    data = []
    for line in lines:
        if line.startswith(":"):
            continue
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event = "message"
            data = []
            continue
        field, _, value = line.partition(":")
        if field == "event":
            event = value.strip()
        elif field == "data":
            data.append(value.lstrip())
    if data:
        yield event, json.loads("\n".join(data))
