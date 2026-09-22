import os
import sys
import tempfile
import threading

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

import diya
import diya_config


def _hostname(host_header):
    """The host name in a Host header, without the port ("[::1]:8080" -> "::1")."""
    value = host_header.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else ""
    return value.split(":", 1)[0]


class BoundaryMiddleware:
    """Answers only requests for an allowed Host name and, when a browser sends an Origin, from an
    allowed origin -- on every route, including the auto-generated docs.

    Host: a request whose Host isn't one of ours (DNS rebinding points an attacker's name at this
    computer) is refused. Origin: a web page from anywhere else on the internet can make the
    user's browser call localhost; without this check it could read the chat history. Requests
    with no Origin (curl, scripts, a server-side proxy) are not browsers, so CSRF doesn't apply.
    """

    def __init__(self, app, allowed_hosts, allowed_origins):
        self.app = app
        self.allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self.allowed_origins = frozenset(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        problem = None
        if _hostname(headers.get(b"host", b"").decode("latin-1")) not in self.allowed_hosts:
            problem = (400, "Invalid host header")
        else:
            origin = headers.get(b"origin")
            if origin is not None and origin.decode("latin-1") not in self.allowed_origins:
                problem = (403, "Origin not allowed")
        if problem is None:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await PlainTextResponse(problem[1], status_code=problem[0])(scope, receive, send)


class BodyLimitMiddleware:
    """Rejects a request body over a configured size with 413, before any route -- or the model --
    ever sees it. Most paths get `default_limit`; a path named in `limit_overrides` gets its own
    (the transcription endpoint's audio uploads are legitimately bigger than a chat message).

    A client-declared Content-Length over the limit is rejected immediately, without reading a
    byte of the body. Otherwise the body is read here and buffered, stopping the instant the
    limit is passed -- so a request with no Content-Length, or one that understates it, cannot get
    more through than an honest one could. A body that fits is handed to the app exactly as
    received, in one piece (the app never sees this middleware was there).
    """

    def __init__(self, app, default_limit, limit_overrides=None):
        self.app = app
        self.default_limit = default_limit
        self.limit_overrides = dict(limit_overrides or {})

    def _limit_for(self, path):
        return self.limit_overrides.get(path, self.default_limit)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope["path"])
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(scope, receive, send, limit)
                    return
            except ValueError:
                pass  # a malformed header is the framework's problem, not ours

        chunks = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                break  # e.g. the client disconnected while we were still reading
            chunk = message.get("body", b"")
            more_body = message.get("more_body", False)
            total += len(chunk)
            if total > limit:
                await self._reject(scope, receive, send, limit)
                return
            chunks.append(chunk)

        body = b"".join(chunks)
        delivered = False

        async def replay_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # the real body is exhausted; only a disconnect is left to hear

        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _reject(scope, receive, send, limit):
        message = f"Request body too large (limit {limit} bytes)"
        await PlainTextResponse(message, status_code=413)(scope, receive, send)


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
    # The UI lives in frontend/ (Next.js, on its own port) and calls this JSON API from the
    # browser, so exactly that origin -- on each allowed host name -- gets CORS access. It used to
    # be "*", which let a page from any website read the chat history through the user's browser.
    allowed_hosts = diya_config.api_allowed_hosts(config)
    allowed_origins = diya_config.api_allowed_origins(config)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    # /api/transcribe carries audio, not JSON, so it gets its own, larger limit (see
    # BodyLimitMiddleware). Added before BoundaryMiddleware below, so it runs after it: a request
    # for the wrong Host or Origin is refused before any effort goes into buffering its body.
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=config.max_body_bytes,
        limit_overrides={"/api/transcribe": config.max_transcribe_bytes},
    )
    # Added last, so it is the outermost layer: nothing (routes, docs, CORS preflights, the body
    # limit above) is reached by a request for the wrong Host or from the wrong Origin.
    app.add_middleware(BoundaryMiddleware, allowed_hosts=allowed_hosts, allowed_origins=allowed_origins)

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
        diya_config.check_exposure(config)
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

    if config.lan:
        print(f"Diya's API is in LAN mode: listening on {config.host}:{config.port}, "
              f"answering to {', '.join(diya_config.api_allowed_hosts(config))}.")
    else:
        print(f"Diya's API is listening on {config.host}:{config.port} (this computer only).")
    uvicorn.run(
        create_app(config, agent, transcriber),
        host=config.host,
        port=config.port,
        ssl_certfile=tls[0],
        ssl_keyfile=tls[1],
    )


if __name__ == "__main__":
    main()
