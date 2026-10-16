"""One summary line per model step and per tool call. The API key is never written."""

import json
import logging
import os
import time

from langchain_core.callbacks import BaseCallbackHandler

log = logging.getLogger("biomeagent")
log.setLevel(logging.INFO)
log.propagate = False
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)

_SECRET = ("key", "token", "secret", "authorization", "password")
_ARG_CAP = 180


class CallLog(BaseCallbackHandler):
    def __init__(self):
        self._started = {}
        self._pending = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._started[run_id] = time.perf_counter()
        count = sum(len(batch) for batch in messages or [])
        self._pending[run_id] = ("llm", _model_name(serialized), count)

    def on_llm_end(self, response, *, run_id, **kwargs):
        kind, model, count = self._pending.pop(run_id, ("llm", _model_name(None), 0))
        tools = ",".join(_tool_names(response))
        extra = f" tools={tools}" if tools else ""
        log.info("llm model=%s messages=%s%s %s", model, count, extra, _elapsed(self._started, run_id))

    def on_llm_error(self, error, *, run_id, **kwargs):
        _, model, count = self._pending.pop(run_id, ("llm", _model_name(None), 0))
        log.info(
            "llm model=%s messages=%s error=%s %s",
            model,
            count,
            _clip(str(error)),
            _elapsed(self._started, run_id),
        )

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        self._started[run_id] = time.perf_counter()
        name = (serialized or {}).get("name") or "tool"
        self._pending[run_id] = ("tool", name, _clip(_safe(inputs if inputs is not None else input_str)))

    def on_tool_end(self, output, *, run_id, **kwargs):
        _, name, args = self._pending.pop(run_id, ("tool", "tool", ""))
        records, error = _outcome(output)
        if error:
            detail = f"error={_clip(error)}"
        elif records is None:
            detail = "records=0"
        else:
            detail = f"records={records}"
        log.info("tool %s args=%s %s %s", name, args, detail, _elapsed(self._started, run_id))

    def on_tool_error(self, error, *, run_id, **kwargs):
        _, name, args = self._pending.pop(run_id, ("tool", "tool", ""))
        log.info(
            "tool %s args=%s error=%s %s",
            name,
            args,
            _clip(str(error)),
            _elapsed(self._started, run_id),
        )


def _model_name(serialized):
    kwargs = (serialized or {}).get("kwargs") or {}
    name = kwargs.get("model") or kwargs.get("model_name")
    if isinstance(name, str) and not any(part in name.lower() for part in _SECRET):
        return name
    return os.getenv("OPENROUTER_MODEL") or "model"


def _tool_names(response):
    names = []
    for generations in getattr(response, "generations", None) or []:
        for generation in generations:
            message = getattr(generation, "message", None)
            for call in getattr(message, "tool_calls", None) or []:
                name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                if name:
                    names.append(name)
    return names


def _outcome(output):
    text = output if isinstance(output, str) else getattr(output, "content", "")
    if not isinstance(text, str):
        text = str(text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    if parsed.get("error"):
        return None, str(parsed["error"])
    records = parsed.get("records")
    if isinstance(records, list):
        return len(records), None
    return None, None


def _safe(value):
    if isinstance(value, dict):
        kept = {
            key: item
            for key, item in value.items()
            if not any(part in key.lower() for part in _SECRET)
        }
        return json.dumps(kept, default=str, ensure_ascii=False)
    return str(value)


def _clip(text):
    flat = " ".join(str(text).split())
    if len(flat) <= _ARG_CAP:
        return flat
    return flat[: _ARG_CAP - 3] + "..."


def _elapsed(started, run_id):
    began = started.pop(run_id, None)
    if began is None:
        return "0ms"
    return f"{int((time.perf_counter() - began) * 1000)}ms"
