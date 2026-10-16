import logging
import uuid
from types import SimpleNamespace

from biomeagent.call_log import CallLog


def test_tool_line_has_args_records_and_duration(caplog):
    caplog.set_level(logging.INFO)
    call_log = CallLog()
    run_id = uuid.uuid4()
    call_log.on_tool_start(
        {"name": "lookup_pubchem"},
        "",
        run_id=run_id,
        inputs={"name": "butyrate", "api_key": "sk-secret"},
    )
    call_log.on_tool_end('{"records": [{"id": "104775"}], "error": null}', run_id=run_id)
    text = caplog.text
    assert "tool lookup_pubchem" in text
    assert "butyrate" in text
    assert "records=1" in text
    assert "ms" in text
    assert "sk-secret" not in text


def test_tool_error_and_llm_step_omit_the_key(caplog):
    caplog.set_level(logging.INFO)
    call_log = CallLog()
    tool_run = uuid.uuid4()
    call_log.on_tool_start({"name": "lookup_bacdive"}, '{"query": "Akkermansia"}', run_id=tool_run)
    call_log.on_tool_end('{"records": [], "error": "timed out"}', run_id=tool_run)

    llm_run = uuid.uuid4()
    call_log.on_chat_model_start(
        {"kwargs": {"model": "google/gemini-3.8-flash", "api_key": "sk-secret"}},
        [[object(), object()]],
        run_id=llm_run,
    )
    message = SimpleNamespace(tool_calls=[{"name": "lookup_pubchem"}])
    response = SimpleNamespace(generations=[[SimpleNamespace(message=message)]])
    call_log.on_llm_end(response, run_id=llm_run)

    text = caplog.text
    assert "tool lookup_bacdive" in text
    assert "error=timed out" in text
    assert "llm model=google/gemini-3.8-flash messages=2 tools=lookup_pubchem" in text
    assert "sk-secret" not in text
