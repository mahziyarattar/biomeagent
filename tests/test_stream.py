import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from biomeagent.agent import Tool, _tools, events_from_graph
from biomeagent.assemble import NO_SOURCE
from biomeagent.http import HttpClient
from biomeagent.main import app
from biomeagent.sse import encode_sse, parse_sse


def test_tokens_and_tool_status_stay_apart_from_the_final_records():
    tool_only = SimpleNamespace(content="", tool_call_chunks=[{"name": "search_europepmc"}])
    text = SimpleNamespace(content="Five papers.", tool_call_chunks=[])
    chunks = [
        ("messages", (tool_only, {"langgraph_node": "agent"})),
        (
            "updates",
            {"agent": {"messages": [SimpleNamespace(tool_calls=[{"name": "search_europepmc"}])]}},
        ),
        ("updates", {"tools": {"messages": []}}),
        ("messages", (text, {"langgraph_node": "agent"})),
        ("messages", (text, {"langgraph_node": "tools"})),
        (
            "values",
            {
                "messages": [
                    {"role": "assistant", "content": "", "tool_calls": [{"name": "search_europepmc"}]},
                    {
                        "role": "tool",
                        "name": "search_europepmc",
                        "content": json.dumps({"records": [{"id": "1"}], "error": None}),
                    },
                    {"role": "assistant", "content": "Five papers."},
                ]
            },
        ),
    ]
    events = list(events_from_graph(chunks))
    assert events[0] == {"type": "status", "message": "Thinking…"}
    assert {"type": "status", "message": "Searching Europe PMC"} in events
    assert events[-2] == {"type": "token", "delta": "Five papers."}
    assert [event for event in events if event["type"] == "token"] == [
        {"type": "token", "delta": "Five papers."}
    ]
    final = events[-1]
    assert final["reply"] == "Five papers."
    assert final["records"] == [{"id": "1"}]
    assert final["errors"] == []


def test_status_sentence_comes_from_the_enum():
    assert {tool.name for tool in _tools(HttpClient())} == {item.name for item in Tool}
    events = list(
        events_from_graph(
            [
                (
                    "updates",
                    {
                        "agent": {
                            "messages": [
                                SimpleNamespace(
                                    tool_calls=[{"name": "lookup_pubchem"}, {"name": "not_a_tool"}]
                                )
                            ]
                        }
                    },
                ),
                ("values", {"messages": []}),
            ]
        )
    )
    assert {"type": "status", "message": "Looking up PubChem"} in events
    assert all("not_a_tool" not in event.get("message", "") for event in events)


def test_failed_tools_replace_streamed_text_on_the_final_event():
    events = list(
        events_from_graph(
            [
                (
                    "messages",
                    (SimpleNamespace(content="I found it.", tool_call_chunks=[]), {"langgraph_node": "agent"}),
                ),
                (
                    "values",
                    {
                        "messages": [
                            {
                                "role": "tool",
                                "name": "lookup_pubchem",
                                "content": json.dumps({"records": [], "error": "timed out"}),
                            }
                        ]
                    },
                ),
            ]
        )
    )
    assert events[-1]["reply"] == NO_SOURCE
    assert events[-1]["records"] == []


def test_stream_route_sends_status_then_tokens_then_done(monkeypatch):
    def fake(_messages):
        yield {"type": "status", "message": "Calling lookup_pubchem"}
        yield {"type": "token", "delta": "Hi"}
        yield {"type": "final", "reply": "Hi", "records": [{"id": "104775"}], "errors": []}

    monkeypatch.setattr("biomeagent.main.run_chat_stream", fake)
    with TestClient(app).stream(
        "POST",
        "/chat/stream",
        json={"messages": [{"role": "user", "content": "hi"}]},
    ) as response:
        assert response.status_code == 200
        parsed = list(parse_sse(response.iter_lines()))
    assert parsed[0] == ("status", {"message": "Calling lookup_pubchem"})
    assert parsed[1] == ("token", {"delta": "Hi"})
    assert parsed[2][0] == "done"
    assert parsed[2][1]["records"] == [{"id": "104775"}]


def test_sse_round_trip():
    lines = (
        encode_sse("status", {"message": "Calling lookup_pubchem"})
        + encode_sse("token", {"delta": "Butyrate"})
        + encode_sse("done", {"reply": "Butyrate", "records": [], "errors": []})
    ).splitlines()
    # splitlines drops the blank line that ends each event; put it back.
    framed = []
    for line in lines:
        framed.append(line)
        if line.startswith("data:"):
            framed.append("")
    parsed = list(parse_sse(framed))
    assert parsed[0] == ("status", {"message": "Calling lookup_pubchem"})
    assert parsed[1] == ("token", {"delta": "Butyrate"})
    assert parsed[2][0] == "done"
