import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import sys
import tempfile
import threading
import traceback

import openai
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

import diya
import diya_actions_api
import diya_brief_api
import diya_categories
import diya_categories_api
import diya_config
import diya_connections_api
import diya_connector_tools
import diya_intent
import diya_health_api
import diya_journal_api
import diya_knowledge_api
import diya_memory_api
import diya_automations_api
import diya_proactive_api
import diya_push_api
import diya_questions_api
import diya_reminders_api
import diya_schedule_api
import diya_tasks_api
import diya_threads_api


# ---- the per-install access token (docs/STAGE1_DESIGN.md section 3) ----
# A random token is generated once and shown once; only its SHA-256 is kept, in a small file. A
# request proves it holds the token by sending `Authorization: Bearer <token>`, which is hashed and
# compared with the stored hash. Nothing here needs the token itself after it has been printed.

def hash_token(token):
    """The SHA-256 of a token, as the lowercase hex string that is stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def read_token_hash(path):
    """The stored token hash (64 hex characters), or None if there is no token file yet. A file
    that exists but doesn't hold a hash is an error, never quietly treated as "no token"."""
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    except FileNotFoundError:
        return None
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise diya_config.ConfigError(
            f"{path} doesn't hold a token hash; delete it to have a new token generated "
            "(or start with --rotate-token)"
        )
    return value


def ensure_token(path, rotate=False):
    """Make sure a token hash is stored at `path`. Returns the new plaintext token if one was just
    generated -- the only moment it exists outside the caller's own memory -- and None if a token
    was already stored. `rotate` replaces an existing one; the old token stops working."""
    if not rotate and read_token_hash(path) is not None:
        return None
    token = secrets.token_urlsafe(32)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        f.write(hash_token(token) + "\n")
    os.replace(temporary, path)  # never leaves a half-written file where the real one was
    return token


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


class TokenMiddleware:
    """When `required`, answers only requests that carry `Authorization: Bearer <token>` for the
    stored token, with 401 and `WWW-Authenticate: Bearer` otherwise -- on every route, including
    the auto-generated docs and routes added later, because it wraps the whole app rather than
    listing paths. It is the outermost layer, so a request with no token is turned away before
    the Host/Origin check, the body limit or any route spends effort on it.

    Only a hash of the token is ever held (`token_hash`, 64 hex characters). The presented token
    is hashed and the two hashes compared with hmac.compare_digest, which takes the same time
    however many leading bytes match. `required` False makes this a pure pass-through, which is
    the default for now. Required with no stored hash refuses everything: it fails closed.
    """

    def __init__(self, app, token_hash, required):
        self.app = app
        self.required = required
        self.token_hash = bytes.fromhex(token_hash) if token_hash else None

    def _authorized(self, headers):
        presented = [value for name, value in headers if name == b"authorization"]
        if self.token_hash is None or len(presented) != 1:  # one credential, exactly
            return False
        parts = presented[0].split(None, 1)
        if len(parts) != 2 or parts[0].lower() != b"bearer":  # the scheme name is case-insensitive
            return False
        return hmac.compare_digest(hashlib.sha256(parts[1]).digest(), self.token_hash)

    async def __call__(self, scope, receive, send):
        if not self.required or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
        elif self._authorized(scope["headers"]):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
        else:
            await PlainTextResponse(
                "Missing or invalid access token",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)


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


MAX_CAPTURE_TRIES = 3  # how many times a message that could not be read (the model was down) is tried before it is left to the scheduled pass
CAPTURE_BATCH = 50  # how many waiting messages are looked at in one go
MAX_PAGE_MESSAGES = 300  # how many of the one chat's newest messages the page is given; the rest are one "earlier" away


class ChatRequest(BaseModel):
    thread_id: int | None = None
    message: str


# What a chat turn that could not be answered says, in words for the person (the page shows them under the message). They are fixed
# text, never the exception's own: that goes to this program's console, where someone looking for the cause can read it.
STREAM_PING_SECONDS = 10.0  # a streamed turn says "still working" this often, so a model that takes half a minute to load does not look like a dead connection
MODEL_DID_NOT_ANSWER = "The model didn’t answer (is Ollama running?), so there is no reply. Your message was kept; try again."
ANSWERING_FAILED = "Something went wrong while answering, so there is no reply. Your message was kept; try again. The details are in the API’s console."
TRANSCRIPTION_FAILED = "That recording could not be turned into text. Try again, or type it. The details are in the API’s console."


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
                # The model is downloaded from Hugging Face the first time; its client reports anonymous usage unless told not to.
                os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            return self._model

    def warm_up(self):
        print("Loading Whisper model...")
        self.model
        print("Whisper ready.")

    def transcribe(self, path):
        """The words in a recording, or "" if nobody spoke in it. Whisper invents text for silence (measured here: four seconds of nothing came back as "You", the same word every time), so
        only the stretches a speech detector finds are read at all (docs/VOICE_DESIGN.md); real speech comes back as it did without it."""
        segments, _ = self.model.transcribe(path, vad_filter=True, vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False)
        return " ".join(s.text for s in segments).strip()


def create_app(config=None, agent=None, transcriber=None, connectors=None):
    """Build the JSON API around an Agent and a transcriber.

    Nothing is loaded here -- the agent and transcriber are lazy, so building an app is free
    and tests can hand in their own (a fake model, a temp database). Defaults come from the
    environment, so `create_app()` with no arguments is the real thing. `connectors` defaults to
    the real registry (Home Assistant, Notion, Todoist as of unit C2); tests hand in fakes the same
    way they hand in a fake model client.
    """
    config = config or diya_config.load_config()
    agent = agent or diya.Agent(config)
    transcriber = transcriber or WhisperTranscriber(config.whisper_model)
    connectors = diya_connector_tools.real_connectors(config) if connectors is None else connectors

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
    # Added after that, so it is outermost of all: a request with no token is refused before the
    # Host/Origin check has spent any effort on it. On unless DIYA_REQUIRE_TOKEN=0 (the stored hash
    # is only read when it is needed, so an app that opted out touches no file).
    app.add_middleware(
        TokenMiddleware,
        token_hash=read_token_hash(config.token_path) if config.require_token else None,
        required=config.require_token,
    )

    @app.get("/api/threads")
    def api_threads():
        main = agent.store.current_main_thread()  # reading the list makes no chat
        return {"threads": [dict(thread, main=thread["id"] == main) for thread in agent.store.list_threads_with_preview()]}

    @app.get("/api/history/{thread_id}")
    def api_history(thread_id: str):
        """A chat's messages. `main` is the one chat (docs/ONE_CHAT_DESIGN.md): its newest MAX_PAGE_MESSAGES, with `more_before` true when older ones are left out. Any other whole number is an
        earlier chat, read as before. `is_main` tells the page whether it may write in what it was given."""
        if thread_id == "main":
            number = main = agent.store.main_thread()
        elif re.fullmatch(r"[0-9]{1,18}", thread_id):
            number, main = int(thread_id), agent.store.current_main_thread()  # looking at an earlier chat makes nothing
        else:
            raise HTTPException(status_code=404, detail="No such thread")
        if number == main:
            messages, more_before = agent.store.get_messages_tail(number, MAX_PAGE_MESSAGES)
            tags = diya_categories.Book(agent.store).tags([m["id"] for m in messages if m["role"] == "user"])
            messages = [dict(m, category=tags[m["id"]]) if m["id"] in tags else m for m in messages]
        else:
            messages, more_before = agent.store.get_messages(number), False  # an earlier chat is read whole; its messages carry ids and categories too (so a tag can be moved)
            tags = diya_categories.Book(agent.store).tags([m["id"] for m in messages if m["role"] == "user"])
            messages = [dict(m, category=tags[m["id"]]) if m["id"] in tags else m for m in messages]
        return {"thread_id": number, "is_main": number == main, "more_before": more_before, "messages": messages}

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
        except Exception:  # a defect, a bad file or a missing model: say so in fixed words, and leave the trace where it can be read
            print("[transcribe] transcribing failed:", file=sys.stderr)
            traceback.print_exc()
            return {"text": "", "error": TRANSCRIPTION_FAILED}
        finally:
            os.remove(tmp_path)

        return {"text": text}

    sorting = diya_categories.SORT_LOCK  # one exchange is sorted at a time, each waiting its turn in a thread of its own so that a chat never waits for it

    def sort_exchange(message_id, text, tools_called):
        """After a reply has been sent: put the person's message in a category (docs/ONE_CHAT_DESIGN.md, step 2). Code decides what it can; the model is asked the rest. It never raises and a failure
        leaves the message with no category, which the page shows as none yet."""
        if not config.categories:
            return
        with sorting:
            try:
                diya_categories.sort(diya_categories.Book(agent.store), agent.client, config.model, message_id, text, tools_called)
            except Exception:  # a label is never worth a chat's trouble
                print("[categories] sorting failed:", file=sys.stderr)
                traceback.print_exc()

    reading_for_facts = threading.Lock()

    def read_one(dreamer, message_id):
        """Read one queued message for facts and settle its place in the queue: done (it is read), skipped (nothing in it worth keeping), or left waiting (the model could not be asked), which after
        MAX_CAPTURE_TRIES tries is left to the scheduled pass."""
        store = agent.store
        try:
            if store.captured_message_ids([message_id]):  # the scheduled pass got there first
                return store.finish_capture(message_id, "done")
            found = [m for m in store.get_messages_between(message_id, message_id) if m["role"] == "user"]
            if not found or not (diya_intent.is_worth_capturing(found[0]["content"]) or diya_intent.forget_target(found[0]["content"]) is not None):
                return store.finish_capture(message_id, "skipped")
            dreamer.capture_message(message_id)
            if store.captured_message_ids([message_id]):
                return store.finish_capture(message_id, "done")
            tries = store.retry_capture(message_id, "the model could not be asked")
        except Exception as exc:  # a failure here must never be what breaks a chat
            print("[capture] reading for facts failed:", file=sys.stderr)
            traceback.print_exc()
            tries = store.retry_capture(message_id, f"{type(exc).__name__}")
        if tries >= MAX_CAPTURE_TRIES:
            store.finish_capture(message_id, "failed", "tried and could not read it; the scheduled pass reads it")

    def read_for_facts(message_id=None):
        """After a reply has been sent: let memory read what the person said for facts at once (docs/AUTO_MEMORY_DESIGN.md unit A4, docs/MEMORY_DURABILITY_DESIGN.md). Every message is already in the
        capture queue, put there when it was saved. One reader at a time, and the one reading takes everything that is waiting, one message after another, looking again before it lets go: a message that
        arrives while another is being read is no longer skipped, it is read next. A chat never waits for this. Only with automatic memory on."""
        while True:
            if not reading_for_facts.acquire(blocking=False):
                return  # the reader will take it: it looks again before it stops
            try:
                import dreaming

                dreamer = dreaming.Dreamer(config, client=agent.client, store=agent.store)
                tried = set()
                while True:
                    waiting = [i for i in agent.store.pending_captures(CAPTURE_BATCH) if i not in tried]
                    if not waiting:
                        break
                    for waiting_id in waiting:
                        tried.add(waiting_id)
                        read_one(dreamer, waiting_id)
            except Exception:  # nothing here is allowed to reach the person
                print("[capture] reading for facts failed:", file=sys.stderr)
                traceback.print_exc()
            finally:
                reading_for_facts.release()
            if not [i for i in agent.store.pending_captures(CAPTURE_BATCH) if i not in tried]:
                return  # nothing arrived while the place was being let go of

    def start_turn(req):
        """The part of a chat turn that comes before the model: the chat (a new one if none was named), the history, and the person's message saved. Returns (thread_id, history, message_id)."""
        thread_id = req.thread_id or agent.store.main_thread()  # no chat named: the one chat (docs/ONE_CHAT_DESIGN.md)
        saved = agent.store.get_messages(thread_id)
        # The same words, from the person, as the last message of this thread, which nothing answered: they are trying again
        # after a failed turn. That message is used again, not saved a second time, so a retry leaves one message, not two.
        retry = bool(saved) and saved[-1]["role"] == "user" and saved[-1]["content"] == req.message
        earlier = saved[:-1] if retry else saved
        history = agent.with_profile([{"role": m["role"], "content": m["content"]} for m in earlier])
        message_id = saved[-1]["id"] if retry else agent.store.add_message(thread_id, "user", req.message)
        if config.auto_memory:
            agent.store.enqueue_capture(message_id)  # written down before the turn is answered: a restart cannot lose it, and the reading that follows takes it in its turn
        history.append({"role": "user", "content": req.message})
        return thread_id, history, message_id

    def end_turn(thread_id, message_id, req, answer):
        """The part after the model: the answer saved, and whether memory will read the message (`reading`, which lets the page ask a little later what it learned)."""
        agent.store.add_message(thread_id, "assistant", answer)
        if config.auto_memory:
            return diya_intent.is_worth_capturing(req.message) or diya_intent.forget_target(req.message) is not None
        return False

    def failure_of(exc):
        """(status, the fixed words) for an exception out of agent.ask, and the trace left in the console."""
        if isinstance(exc, openai.OpenAIError):  # nothing listening, a timeout, an error from Ollama itself
            print(f"[chat] the model did not answer ({type(exc).__name__}: {exc})", file=sys.stderr)
            return 503, MODEL_DID_NOT_ANSWER
        print("[chat] answering failed:", file=sys.stderr)  # a defect here, not the model's doing: say so, and leave the trace where it can be read
        traceback.print_exception(exc)
        return 500, ANSWERING_FAILED

    @app.post("/api/chat")
    def chat(req: ChatRequest, background: BackgroundTasks):
        thread_id, history, message_id = start_turn(req)
        try:
            answer, tools_called = agent.ask(history, thread_id=thread_id, message_id=message_id)
        except Exception as exc:
            status, detail = failure_of(exc)
            return JSONResponse({"detail": detail, "thread_id": thread_id}, status_code=status)
        reading = end_turn(thread_id, message_id, req, answer)
        background.add_task(sort_exchange, message_id, req.message, tools_called)  # after the response is on its way, never before it
        if config.auto_memory:
            background.add_task(read_for_facts, message_id)  # runs after the response is on its way, never before it
        # `message_id` and `reading` let the page ask, a little later, what memory did with the message (GET /api/memory/learned)
        return {"thread_id": thread_id, "answer": answer, "tools_called": tools_called, "message_id": message_id, "reading": reading}

    @app.post("/api/chat/stream")
    def chat_stream(req: ChatRequest):
        """The same turn as /api/chat, told as it happens (docs/STREAMING_DESIGN.md): one JSON object per line, `start` (the chat and the saved message), then `delta` pieces of the reply
        (`reset` takes them back if they were a preface to a tool, `tool` says one is running, `wait` says it is still working), then `done` with exactly what /api/chat returns, or `error` with
        the reason and the chat the message was kept in. What is wrong before the model is asked is an ordinary HTTP error. The turn runs in ONE thread of its own, because what a turn knows
        about the message it is answering is kept per thread; the response only reads what that thread says."""
        thread_id, history, message_id = start_turn(req)
        events = queue.Queue()

        def work():
            try:
                answer, tools_called = agent.ask(history, thread_id=thread_id, message_id=message_id, on_event=lambda kind, payload: events.put((kind, payload)))
                reading = end_turn(thread_id, message_id, req, answer)
            except Exception as exc:
                events.put(("error", failure_of(exc)))
                return
            events.put(("done", {"thread_id": thread_id, "answer": answer, "tools_called": tools_called, "message_id": message_id, "reading": reading}))
            sort_exchange(message_id, req.message, tools_called)  # after the last line is on its way
            if config.auto_memory:
                read_for_facts(message_id)  # after the last line is on its way, as /api/chat's background task is

        worker = threading.Thread(target=work, name="chat-turn", daemon=True)
        worker.start()

        def line(obj):
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"

        def lines():
            yield line({"type": "start", "thread_id": thread_id, "message_id": message_id})
            while True:
                try:
                    kind, payload = events.get(timeout=STREAM_PING_SECONDS)
                except queue.Empty:
                    if not worker.is_alive() and events.empty():  # the turn ended without a word: never leave the page waiting
                        yield line({"type": "error", "status": 500, "detail": ANSWERING_FAILED, "thread_id": thread_id})
                        return
                    yield line({"type": "wait"})
                    continue
                if kind == "delta":
                    yield line({"type": "delta", "text": payload})
                elif kind == "reset":
                    yield line({"type": "reset"})
                elif kind == "tool":
                    yield line({"type": "tool", "name": payload})
                elif kind == "done":
                    yield line({"type": "done", **payload})
                    return
                elif kind == "error":
                    yield line({"type": "error", "status": payload[0], "detail": payload[1], "thread_id": thread_id})
                    return

        return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    # Reviewing what Dreaming staged (docs/STAGE2_DESIGN.md, unit 6): the same rules as diya_review.py.
    diya_memory_api.register(app, config, agent)
    diya_questions_api.register(app, config, agent)  # the questions Diya raises herself (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5)
    diya_proactive_api.register(app, config, agent)  # what Diya wrote first (docs/PROACTIVE_DESIGN.md)
    diya_automations_api.register(app, config, agent)  # what Diya does on a schedule for the person (docs/AUTOMATIONS_DESIGN.md)
    diya_knowledge_api.register(app, config, agent)  # the pages made from the person's notes (docs/KNOWLEDGE_DESIGN.md)
    diya_threads_api.register(app, config, agent)  # searching and naming past chats
    diya_journal_api.register(app, config, agent)  # what Diya did with a tool or a connector (docs/ACTIVITY_JOURNAL_DESIGN.md)
    diya_health_api.register(app, config, agent)  # is Diya well, one honest line per part (docs/HEALTH_DESIGN.md)
    diya_categories_api.register(app, config, agent, lambda: MAX_PAGE_MESSAGES)  # the one chat by category (docs/ONE_CHAT_DESIGN.md, steps 2 and 3)
    diya_push_api.register(app, config, agent)  # telling the phone by Web Push, off unless DIYA_PUSH=1 (docs/PUSH_DESIGN.md, unit P2)
    diya_reminders_api.register(app, config, agent)
    diya_tasks_api.register(app, config, agent)  # the to-do list inside Diya (docs/TASKS_DESIGN.md, unit T2)
    diya_schedule_api.register(app, config, agent)  # repeating reminders and snooze (docs/SCHEDULE_DESIGN.md, unit R4)
    diya_brief_api.register(app, config, agent)  # the day: what is due, overdue and coming (docs/SCHEDULE_DESIGN.md, unit R5)
    diya_connections_api.register(app, config, agent, connectors=connectors)
    # Deciding what Diya proposed (docs/ACTIONS_DESIGN.md, unit A3): the agent carries the action store and its kinds.
    diya_actions_api.register(app, config, agent)

    return app


def main():
    import uvicorn

    diya.configure_console()
    try:
        config = diya_config.load_config()
        diya_config.check_exposure(config)
        diya_config.ensure_data_dir(config)
        tls = diya_config.tls_files(config)
    except (diya_config.ConfigError, OSError) as exc:
        print(f"Couldn't start Diya's server: {exc}.")
        sys.exit(1)
    if tls is None:
        # The frontend and iPhone microphone access both need HTTPS, so refuse to start rather
        # than quietly serving plain HTTP.
        print("Couldn't start Diya's server: no TLS certificate found.")
        print("Put an mkcert pair (<name>+N.pem and <name>+N-key.pem) in this folder, "
              "or set DIYA_SSL_CERT and DIYA_SSL_KEY.")
        sys.exit(1)

    # Only once the server is known to be startable, so a run that refuses to start never mints a
    # token nobody was shown. The plaintext is printed here, at the moment it exists, and nowhere
    # else: only its hash is stored.
    rotate = config.rotate_token or "--rotate-token" in sys.argv[1:]
    try:
        new_token = ensure_token(config.token_path, rotate=rotate)
    except (diya_config.ConfigError, OSError) as exc:
        print(f"Couldn't start Diya's server: {exc}.")
        sys.exit(1)
    if new_token:
        print("A new access token was generated for Diya's API. Save it now: it is shown only this "
              f"once, and only its hash is kept (in {config.token_path}).")
        if rotate:
            print("The previous token no longer works.")
        print(f"    {new_token}")
        if config.require_token:
            print("The API requires it: send it as 'Authorization: Bearer <token>'. The UI needs it too: "
                  "set DIYA_TOKEN to it (see docs/lan.md), then restart the UI.")
        else:
            print("DIYA_REQUIRE_TOKEN=0: nothing requires it.")

    agent = diya.Agent(config)
    diya.warm_up_or_exit(agent)
    for line in diya.memory_startup_lines(agent) + diya.actions_startup_lines(agent):
        print(line)
    if config.backup:  # a checked snapshot of the memory when the newest is a day old, and then once a day (diya_backup.py, docs/BACKUP_DESIGN.md)
        import diya_backup

        diya_backup.Daily(config).start()
    transcriber = WhisperTranscriber(config.whisper_model)
    transcriber.warm_up()
    if config.keep_warm:  # load the chat model now and keep it loaded, so the first message is not the slow one (docs/SPEED_DESIGN.md)
        import diya_warm

        diya_warm.KeepWarm(config, agent).start()

    if config.lan:
        print(f"Diya's API is in LAN mode: listening on {config.host}:{config.port}, "
              f"answering to {', '.join(diya_config.api_allowed_hosts(config))}.")
    else:
        print(f"Diya's API is listening on {config.host}:{config.port} (this computer only).")
    if config.require_token and new_token is None:
        # not the first start, so the token isn't shown again: say where it went, and how to replace it
        print("It requires the access token that was shown at first start (--rotate-token replaces a "
              "lost one; DIYA_REQUIRE_TOKEN=0 turns the requirement off).")
    uvicorn.run(
        create_app(config, agent, transcriber),
        host=config.host,
        port=config.port,
        ssl_certfile=tls[0],
        ssl_keyfile=tls[1],
    )


if __name__ == "__main__":
    main()
