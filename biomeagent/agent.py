"""LangGraph ReAct agent. The model chooses tools and writes the reply."""

import json
import os
from enum import Enum
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from biomeagent import sources
from biomeagent.assemble import assemble
from biomeagent.call_log import CallLog
from biomeagent.http import HttpClient

STEP_LIMIT = 8


class Tool(Enum):
    """Status text for a tool. The member name is the name the model calls."""

    search_europepmc = "Searching Europe PMC"
    annotate_paper = "Reading paper mentions"
    lookup_pubchem = "Looking up PubChem"
    lookup_vmh = "Looking up VMH"
    search_trials = "Searching ClinicalTrials.gov"
    lookup_bacdive = "Looking up BacDive"
    lookup_taxon = "Looking up NCBI Taxonomy"
    lookup_omnipath = "Looking up OmniPath"

SYSTEM = """
You are BiomeAgent, a thesis assistant. Answer from the tool results for this turn.

Call a tool when the fact should come from a paper, a text-mined mention, a chemical record, a metabolic-model entry, a registered trial, a strain sheet, a taxonomy record, or a chemical-protein interaction. Pass the name or identifier you mean. Butyrate and butyric acid are different compounds. If the person greets you or asks who you are, answer in their language and do not call a tool.

A preparation is an inanimate microorganism or its components. A metabolite is a chemical a microbe makes. Keep those words apart. An OmniPath record is a chemical-protein interaction, not a statement that a probiotic regulates a host gene. An annotation is a mention in the text, not a curated cause.

Write a chemical formula as plain characters, such as C4H7O2-, not as math notation. Do not invent an identifier that no tool returned. Do not give a personal dose or a medical instruction. You may quote a dose or duration only when that string is already in an abstract, an open-access full text, or a trial intervention text. Do not send the bare word heat-killed to ClinicalTrials.gov, because that query also matches vaccines.
""".strip()


def _load_env():
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if " #" in value:
            value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


def run_chat(messages):
    missing = _missing_model()
    if missing:
        return missing
    agent = create_react_agent(_model(), _tools(HttpClient()), prompt=SYSTEM)
    result = agent.invoke(
        {"messages": _history(messages)},
        config={"recursion_limit": STEP_LIMIT * 2 + 2, "callbacks": [CallLog()]},
    )
    return assemble(result["messages"])


def run_chat_stream(messages):
    """Yield status, token, and final events for one turn. Records stay on the final event."""
    missing = _missing_model()
    if missing:
        yield {"type": "final", **missing}
        return
    agent = create_react_agent(_model(streaming=True), _tools(HttpClient()), prompt=SYSTEM)
    graph = agent.stream(
        {"messages": _history(messages)},
        config={"recursion_limit": STEP_LIMIT * 2 + 2, "callbacks": [CallLog()]},
        stream_mode=["messages", "updates", "values"],
    )
    yield from events_from_graph(graph)


def events_from_graph(chunks):
    yield {"type": "status", "message": "Thinking…"}
    messages = []
    for mode, chunk in chunks:
        if mode == "messages":
            delta = _visible_delta(chunk)
            if delta:
                yield {"type": "token", "delta": delta}
        elif mode == "updates":
            status = _status_from_update(chunk)
            if status:
                yield {"type": "status", "message": status}
        elif mode == "values" and isinstance(chunk, dict):
            messages = chunk.get("messages") or []
    yield {"type": "final", **assemble(messages)}


def _missing_model():
    _load_env()
    if os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_MODEL"):
        return None
    return {
        "reply": "The model is not configured.",
        "records": [],
        "errors": [
            {
                "tool": "agent",
                "message": "Set OPENROUTER_API_KEY and OPENROUTER_MODEL to a model that can call tools.",
            }
        ],
    }


def _visible_delta(chunk):
    if not isinstance(chunk, tuple) or len(chunk) != 2:
        return ""
    message, metadata = chunk
    if not isinstance(metadata, dict) or metadata.get("langgraph_node") != "agent":
        return ""
    text = _chunk_text(message)
    if getattr(message, "tool_call_chunks", None) and not text:
        return ""
    return text


def _status_from_update(chunk):
    if not isinstance(chunk, dict):
        return ""
    labels = [_status_label(name) for name in _tool_names(chunk.get("agent"))]
    labels = [label for label in labels if label]
    if labels:
        return ", ".join(labels)
    if "tools" in chunk:
        return "Thinking…"
    return ""


def _status_label(name):
    try:
        return Tool[name].value
    except KeyError:
        return ""


def _tool_names(agent_update):
    if not isinstance(agent_update, dict):
        return []
    names = []
    for message in agent_update.get("messages") or []:
        calls = getattr(message, "tool_calls", None) or []
        if isinstance(message, dict):
            calls = message.get("tool_calls") or calls
        for call in calls:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                names.append(name)
    return names


def _chunk_text(message):
    content = getattr(message, "content", "") if not isinstance(message, dict) else message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") not in {"tool_use", "tool_call", "tool_call_chunk"}:
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _model(streaming=False):
    return ChatOpenAI(
        model=os.environ["OPENROUTER_MODEL"],
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        streaming=streaming,
    )


def _tools(http):
    @tool
    def search_europepmc(query: str) -> str:
        """Search Europe PMC. Returns up to five papers with PMID, title, and a short excerpt."""
        return json.dumps(sources.search_europepmc(query, http=http))

    @tool
    def annotate_paper(pmid: str) -> str:
        """Text-mined mentions for one PMID. These are mentions, not curated effects."""
        return json.dumps(sources.annotate_paper(pmid, http=http))

    @tool
    def lookup_pubchem(name: str) -> str:
        """Look up a chemical in PubChem by name. Returns the CID, title, and formula."""
        return json.dumps(sources.lookup_pubchem(name, http=http))

    @tool
    def lookup_vmh(name: str) -> str:
        """Look up a metabolite in VMH by name. Returns the abbreviation, formula, reactions, and microbes."""
        return json.dumps(sources.lookup_vmh(name, http=http))

    @tool
    def search_trials(query: str) -> str:
        """Search ClinicalTrials.gov. Do not send the bare word heat-killed."""
        return json.dumps(sources.search_trials(query, http=http))

    @tool
    def lookup_bacdive(query: str) -> str:
        """Look up a living strain in BacDive by genus and species, or by a culture-collection number."""
        return json.dumps(sources.lookup_bacdive(query, http=http))

    @tool
    def lookup_taxon(name: str) -> str:
        """Look up an organism in NCBI Taxonomy. Returns the taxonomy id, name, and rank."""
        return json.dumps(sources.lookup_taxon(name, http=http))

    @tool
    def lookup_omnipath(compound: str, protein: str = "") -> str:
        """Chemical-protein interactions from OmniPath. compound is a name or PubChem CID. protein is optional."""
        return json.dumps(sources.lookup_omnipath(compound, protein=protein, http=http))

    return [
        search_europepmc,
        annotate_paper,
        lookup_pubchem,
        lookup_vmh,
        search_trials,
        lookup_bacdive,
        lookup_taxon,
        lookup_omnipath,
    ]


def _history(messages):
    converted = []
    for message in messages:
        content = message.get("content") or ""
        if message.get("role") == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted
