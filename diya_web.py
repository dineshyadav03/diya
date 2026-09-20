import os
import tempfile

import diya
import diya_db
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()
# The actual UI now lives in frontend/ (Next.js, on its own port) -- this
# server is a pure JSON API. No allow_credentials, so a wildcard origin is
# fine here; this only ever runs on the local LAN, never the open internet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at server startup, not per-request -- loading takes ~60s the first time
# (downloading the model) and would make every voice message painfully slow otherwise.
print("Loading Whisper model...")
from faster_whisper import WhisperModel

whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
print("Whisper ready.")


class ChatRequest(BaseModel):
    thread_id: int | None = None
    message: str


@app.get("/api/threads")
def api_threads():
    return {"threads": diya_db.list_threads_with_preview()}


@app.get("/api/history/{thread_id}")
def api_history(thread_id: int):
    return {"messages": diya_db.get_history(thread_id)}


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    # Match the real format the browser actually sent -- iOS Safari uses MP4/AAC, not webm.
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        segments, _ = whisper_model.transcribe(tmp_path)
        text = " ".join(s.text for s in segments).strip()
    except Exception as exc:
        return {"text": "", "error": str(exc)}
    finally:
        os.remove(tmp_path)

    return {"text": text}


@app.post("/api/chat")
def chat(req: ChatRequest):
    thread_id = req.thread_id or diya_db.create_thread()
    history = diya.with_profile(diya_db.get_history(thread_id))
    diya_db.add_message(thread_id, "user", req.message)
    history.append({"role": "user", "content": req.message})
    try:
        answer, tools_called = diya.ask(history)
    except Exception as exc:
        answer = f"Couldn't reach the model ({exc}). Try again in a moment."
        tools_called = []
    else:
        diya_db.add_message(thread_id, "assistant", answer)
    return {"thread_id": thread_id, "answer": answer, "tools_called": tools_called}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080,
        ssl_certfile="192.168.0.174+2.pem",
        ssl_keyfile="192.168.0.174+2-key.pem",
    )
