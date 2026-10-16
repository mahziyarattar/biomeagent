"""Copy records out of this turn's tool trace. The model does not write them."""

import json

NO_SOURCE = "No source returned anything."


def assemble(messages):
    tool_messages = [message for message in messages if _role(message) == "tool"]
    records = []
    errors = []
    calls = []
    successes = 0
    for message in tool_messages:
        parsed, problem = _parse(message)
        name = _name(message)
        if problem:
            errors.append({"tool": name, "message": problem})
            calls.append({"tool": name, "records": [], "error": problem})
            continue
        if parsed.get("error"):
            errors.append({"tool": name, "message": parsed["error"]})
            calls.append({"tool": name, "records": [], "error": parsed["error"]})
            continue
        successes += 1
        got = parsed.get("records") or []
        records.extend(got)
        calls.append({"tool": name, "records": got, "error": None})
    reply = _reply(messages)
    if not tool_messages:
        reply = reply or NO_SOURCE
    elif successes == 0:
        reply = NO_SOURCE
    return {"reply": reply, "records": records, "errors": errors, "calls": calls}


def _parse(message):
    content = _content(message)
    if isinstance(content, dict):
        return content, None
    try:
        return json.loads(content), None
    except (TypeError, json.JSONDecodeError):
        return None, "the tool return was not a record list"


def _reply(messages):
    text = ""
    for message in messages:
        if _role(message) == "assistant" and _content(message):
            text = _content(message)
    return text


def _role(message):
    if isinstance(message, dict):
        return message.get("role")
    kind = getattr(message, "type", "")
    if kind == "tool":
        return "tool"
    if kind in {"ai", "assistant"}:
        return "assistant"
    return kind


def _content(message):
    if isinstance(message, dict):
        return message.get("content") or ""
    content = getattr(message, "content", "") or ""
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return content


def _name(message):
    if isinstance(message, dict):
        return message.get("name") or "tool"
    return getattr(message, "name", None) or "tool"
