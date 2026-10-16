"""FastAPI entry point. The process keeps no chat session."""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from biomeagent.agent import run_chat, run_chat_stream
from biomeagent.sse import encode_sse

app = FastAPI(title="BiomeAgent")


class ChatRequest(BaseModel):
    messages: list[dict]


@app.post("/chat")
def chat(body: ChatRequest):
    return run_chat(body.messages)


@app.post("/chat/stream")
def chat_stream(body: ChatRequest):
    def generate():
        try:
            for event in run_chat_stream(body.messages):
                kind = event["type"]
                if kind == "status":
                    yield encode_sse("status", {"message": event["message"]})
                elif kind == "token":
                    yield encode_sse("token", {"delta": event["delta"]})
                elif kind == "final":
                    yield encode_sse(
                        "done",
                        {
                            "reply": event["reply"],
                            "records": event["records"],
                            "errors": event["errors"],
                            "calls": event.get("calls") or [],
                        },
                    )
        except Exception as exc:
            yield encode_sse("error", {"detail": str(exc) or exc.__class__.__name__})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
