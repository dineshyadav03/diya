import os
import sys
import tempfile
import threading

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import diya
import diya_config


class ChatRequest(BaseModel):
    thread_id: int | None = None
    message: str


class WhisperTranscriber:
    """Speech-to-text. The model is loaded on first use (or by warm_up() at server start),
    not when this module is imported -- loading takes ~60s the first time (downloading the
    model) and would make every voice message painfully slow if done per-request."""

    def __init__(self, model_name="base"):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            return self._model

    def warm_up(self):
        print("Loading Whisper model...")
        self.model
        print("Whisper ready.")

    def transcribe(self, path):
        segments, _ = self.model.transcribe(path)
        return " ".join(s.text for s in segments).strip()


def create_app(config=None, agent=None, transcriber=None):
    """Build the JSON API around an Agent and a transcriber.

    Nothing is loaded here -- the agent and transcriber are lazy, so building an app is free
    and tests can hand in their own (a fake model, a temp database). Defaults come from the
    environment, so `create_app()` with no arguments is the real thing.
    """
    config = config or diya_config.load_config()
    agent = agent or diya.Agent(config)
    transcriber = transcriber or WhisperTranscriber(config.whisper_model)

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

    @app.get("/api/threads")
    def api_threads():
        return {"threads": agent.store.list_threads_with_preview()}

    @app.get("/api/history/{thread_id}")
    def api_history(thread_id: int):
        return {"messages": agent.store.get_history(thread_id)}

    @app.post("/api/transcribe")
    async def transcribe(audio: UploadFile = File(...)):
        audio_bytes = await audio.read()
        # Match the real format the browser actually sent -- iOS Safari uses MP4/AAC, not webm.
        suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            text = transcriber.transcribe(tmp_path)
        except Exception as exc:
            return {"text": "", "error": str(exc)}
        finally:
            os.remove(tmp_path)

        return {"text": text}

    @app.post("/api/chat")
    def chat(req: ChatRequest):
        thread_id = req.thread_id or agent.store.create_thread()
        history = agent.with_profile(agent.store.get_history(thread_id))
        agent.store.add_message(thread_id, "user", req.message)
        history.append({"role": "user", "content": req.message})
        try:
            answer, tools_called = agent.ask(history)
        except Exception as exc:
            answer = f"Couldn't reach the model ({exc}). Try again in a moment."
            tools_called = []
        else:
            agent.store.add_message(thread_id, "assistant", answer)
        return {"thread_id": thread_id, "answer": answer, "tools_called": tools_called}

    return app


def main():
    import uvicorn

    diya.configure_console()
    try:
        config = diya_config.load_config()
        tls = diya_config.tls_files(config)
    except diya_config.ConfigError as exc:
        print(f"Couldn't start Diya's server: {exc}.")
        sys.exit(1)
    if tls is None:
        # The frontend and iPhone microphone access both need HTTPS, so refuse to start rather
        # than quietly serving plain HTTP.
        print("Couldn't start Diya's server: no TLS certificate found.")
        print("Put an mkcert pair (<name>+N.pem and <name>+N-key.pem) in this folder, "
              "or set DIYA_SSL_CERT and DIYA_SSL_KEY.")
        sys.exit(1)

    agent = diya.Agent(config)
    diya.warm_up_or_exit(agent)
    transcriber = WhisperTranscriber(config.whisper_model)
    transcriber.warm_up()

    uvicorn.run(
        create_app(config, agent, transcriber),
        host=config.host,
        port=config.port,
        ssl_certfile=tls[0],
        ssl_keyfile=tls[1],
    )


if __name__ == "__main__":
    main()
