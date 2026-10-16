"""Chat window. History stays in the browser session. The API does not."""

import base64
import os
from pathlib import Path

import httpx
import streamlit as st

from biomeagent.agent import Tool
from biomeagent.direction import message_view
from biomeagent.sse import parse_sse

API_URL = os.getenv("BIOMEAGENT_API_URL", "http://127.0.0.1:8000")


def _api_error(message):
    return {
        "reply": "The assistant service did not respond.",
        "records": [],
        "errors": [{"tool": "api", "message": message}],
        "calls": [{"tool": "api", "records": [], "error": message}],
    }


def _font_face(weight, filename):
    path = Path(__file__).resolve().parent / "biomeagent" / "fonts" / filename
    if not path.is_file():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return (
        "@font-face{"
        "font-family:Vazir;"
        f"src:url(data:font/woff2;base64,{encoded}) format('woff2');"
        f"font-weight:{weight};"
        "font-style:normal;"
        "font-display:swap;"
        "}"
    )


_FIELDS = (
    ("id", "Id"),
    ("kind", "Kind"),
    ("formula", "Formula"),
    ("rank", "Rank"),
    ("protein", "Protein"),
    ("culture", "Culture"),
    ("databases", "Databases"),
    ("pmids", "PubMed"),
    ("reactions", "Reactions"),
    ("microbes", "Microbes"),
)


def _call_label(name):
    try:
        return Tool[name].value
    except KeyError:
        if name == "api":
            return "The assistant service"
        return "Source"


def _calls(trace):
    if trace.get("calls") is not None:
        return trace["calls"]
    calls = []
    records = trace.get("records") or []
    if records:
        calls.append({"tool": "agent", "records": records, "error": None})
    for error in trace.get("errors") or []:
        calls.append(
            {
                "tool": error.get("tool") or "api",
                "records": [],
                "error": error.get("message"),
            }
        )
    return calls


def _field_text(value):
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    return str(value)


def _show_sources(trace):
    calls = _calls(trace)
    if not calls:
        return
    with st.expander("Sources", expanded=False):
        for call in calls:
            with st.expander(_call_label(call.get("tool")), expanded=False):
                if call.get("error"):
                    st.markdown(call["error"])
                records = call.get("records") or []
                if not records and not call.get("error"):
                    st.markdown("No records.")
                for record in records:
                    name = record.get("name") or record.get("title") or "Record"
                    st.markdown(f"**{name}**")
                    for key, label in _FIELDS:
                        if key not in record or record[key] in ("", None):
                            continue
                        st.markdown(f"{label}: `{_field_text(record[key])}`")
                    title = record.get("title") or ""
                    if title and title != record.get("name"):
                        st.markdown(f"Title: {title}")
                    excerpt = record.get("excerpt") or ""
                    if excerpt:
                        st.markdown(excerpt)


def _show(target, text):
    kind, body = message_view(text)
    if kind == "html":
        target.markdown(body, unsafe_allow_html=True)
    else:
        target.markdown(body)


st.set_page_config(page_title="BiomeAgent", layout="wide")
st.markdown(
    "<style>"
    + _font_face(400, "Vazirmatn-Regular.woff2")
    + _font_face(700, "Vazirmatn-Bold.woff2")
    + """
[data-testid="stChatMessage"] [dir="rtl"] {
  font-family: Vazir, sans-serif;
  text-align: start;
}
[data-testid="stChatMessage"] [dir="rtl"] ul,
[data-testid="stChatMessage"] [dir="rtl"] ol {
  text-align: start;
  padding-left: 0;
  padding-inline-start: 1.5rem;
}
[data-testid="stChatMessage"] [dir="rtl"] pre,
[data-testid="stChatMessage"] [dir="rtl"] code {
  direction: ltr;
  unicode-bidi: isolate;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
""",
    unsafe_allow_html=True,
)
st.title("BiomeAgent")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "traces" not in st.session_state:
    st.session_state.traces = []

for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        _show(st, message["content"])
        if message["role"] == "assistant" and index < len(st.session_state.traces):
            _show_sources(st.session_state.traces[index])

prompt = st.chat_input("Ask about a microbe, a metabolite, a paper, or a trial")
if prompt:
    history = [
        {"role": message["role"], "content": message["content"]}
        for message in st.session_state.messages
    ]
    history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        _show(st, prompt)
    with st.chat_message("assistant"):
        status_slot = st.empty()
        reply_slot = st.empty()
        trace_slot = st.empty()
        status_slot.caption("Thinking…")
        reply = ""
        body = None
        try:
            timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
            with httpx.stream(
                "POST",
                f"{API_URL}/chat/stream",
                json={"messages": history},
                timeout=timeout,
            ) as response:
                response.raise_for_status()
                for event, data in parse_sse(response.iter_lines()):
                    if event == "status":
                        status_slot.caption(data.get("message") or "Thinking…")
                    elif event == "token":
                        status_slot.empty()
                        reply += data.get("delta") or ""
                        _show(reply_slot, reply)
                    elif event == "done":
                        body = data
                    elif event == "error":
                        body = _api_error(data.get("detail") or "stream failed")
        except httpx.HTTPError as exc:
            body = _api_error(str(exc))
        if body is None:
            body = _api_error("the stream ended before a reply")
        status_slot.empty()
        _show(reply_slot, body.get("reply") or "")
        trace = {"calls": body.get("calls") or _calls(body)}
        with trace_slot.container():
            _show_sources(trace)
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.session_state.traces.append({"records": [], "errors": []})
    st.session_state.messages.append({"role": "assistant", "content": body.get("reply") or ""})
    st.session_state.traces.append(trace)
    st.rerun()
