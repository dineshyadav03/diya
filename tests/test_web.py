import dataclasses
import os
import sys
import types

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from fakes import FakeClient, text_reply

DEAD_OLLAMA = {"DIYA_OLLAMA_URL": "http://127.0.0.1:9/v1"}


class FakeTranscriber:
    def __init__(self, text="hello world", error=None):
        self.text, self.error, self.calls = text, error, []

    def transcribe(self, path):
        self.calls.append({"path": path, "existed": os.path.exists(path)})
        if self.error:
            raise self.error
        return self.text


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "web.db"),
        profile_path=str(tmp_path / "web_profile.txt"),
    )


def build(config, *replies, transcriber=None):
    model = FakeClient(replies)
    agent = diya.Agent(config, client=model)
    transcriber = transcriber or FakeTranscriber()
    return TestClient(diya_web.create_app(config, agent, transcriber)), agent, model, transcriber


# --- importing and building are free of side effects -------------------------------

def test_importing_diya_web_loads_nothing(run_python, tmp_path):
    code = (
        "import sys, diya_web\n"
        "assert 'faster_whisper' not in sys.modules, 'Whisper was loaded at import time'\n"
        "assert 'chromadb' not in sys.modules\n"
        "print('ok')\n"
    )
    result = run_python(code, env=DEAD_OLLAMA)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"  # in particular no "Loading Whisper model..."
    assert list(tmp_path.iterdir()) == []


def test_building_the_default_app_touches_nothing(run_python, tmp_path):
    code = (
        "import sys, diya_web\n"
        "diya_web.create_app()\n"
        "assert 'faster_whisper' not in sys.modules\n"
        "print('ok')\n"
    )
    result = run_python(code, env=DEAD_OLLAMA)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
    assert list(tmp_path.iterdir()) == []


def test_the_default_app_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DIYA_DB_PATH", str(tmp_path / "env.db"))
    client = TestClient(diya_web.create_app(transcriber=FakeTranscriber()))
    assert client.get("/api/threads").json() == {"threads": []}
    assert (tmp_path / "env.db").exists()


# --- routes ---------------------------------------------------------------------------

def test_threads_and_history_come_from_the_agents_own_store(config):
    client, agent, _, _ = build(config)
    empty = agent.store.create_thread()
    t = agent.store.create_thread()
    agent.store.add_message(t, "user", "first question")
    agent.store.add_message(t, "assistant", "first answer")

    threads = client.get("/api/threads").json()["threads"]
    assert [x["id"] for x in threads] == [t, empty]
    assert threads[0]["preview"] == "first question"
    assert client.get(f"/api/history/{t}").json() == {
        "messages": [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
    }
    assert client.get("/api/history/9999").json() == {"messages": []}


def test_chat_without_a_thread_creates_one_and_saves_both_messages(config):
    client, agent, model, _ = build(config, text_reply("Four."))
    body = client.post("/api/chat", json={"message": "2+2?"}).json()
    assert body == {"thread_id": 1, "answer": "Four.", "tools_called": []}
    assert agent.store.get_history(1) == [
        {"role": "user", "content": "2+2?"},
        {"role": "assistant", "content": "Four."},
    ]
    assert model.chat_calls[0]["model"] == "qwen2.5:3b"


def test_chat_continues_an_existing_thread_with_its_history(config):
    client, agent, model, _ = build(config, text_reply("Because."))
    t = agent.store.create_thread()
    agent.store.add_message(t, "user", "earlier")
    agent.store.add_message(t, "assistant", "earlier answer")
    body = client.post("/api/chat", json={"thread_id": t, "message": "why?"}).json()
    assert body["thread_id"] == t
    sent = model.chat_calls[0]["messages"]
    assert [m["content"] for m in sent] == ["earlier", "earlier answer", "why?"]
    assert len(agent.store.get_history(t)) == 4


def test_chat_reports_tools_that_were_called(config):
    from fakes import tool_reply

    client, agent, _, _ = build(
        config, tool_reply("add_reminder", '{"content": "call mom"}'), text_reply("Saved.")
    )
    body = client.post("/api/chat", json={"message": "remind me to call mom"}).json()
    assert body["tools_called"] == ["add_reminder"]
    assert [r[1] for r in agent.store.list_reminders()] == ["call mom"]


def test_chat_injects_the_profile_but_never_saves_it(config, tmp_path):
    (tmp_path / "web_profile.txt").write_text("Plays guitar.")
    client, agent, model, _ = build(config, text_reply("Nice."))
    body = client.post("/api/chat", json={"message": "hi"}).json()
    sent = model.chat_calls[0]["messages"]
    assert sent[0] == {"role": "system", "content": "What you know about the user so far:\nPlays guitar."}
    assert all(m["role"] != "system" for m in agent.store.get_history(body["thread_id"]))


def test_chat_survives_a_model_failure_and_keeps_the_users_message(config):
    client, agent, _, _ = build(config)  # no scripted replies: the fake client raises IndexError
    body = client.post("/api/chat", json={"message": "hello?"}).json()
    assert body["answer"].startswith("Couldn't reach the model (")
    assert body["tools_called"] == []
    assert agent.store.get_history(body["thread_id"]) == [{"role": "user", "content": "hello?"}]


def test_transcribe_passes_the_audio_to_the_transcriber_and_cleans_up(config):
    client, _, _, transcriber = build(config, transcriber=FakeTranscriber("turn on the lights"))
    response = client.post("/api/transcribe", files={"audio": ("clip.m4a", b"fake-audio", "audio/mp4")})
    assert response.json() == {"text": "turn on the lights"}
    call = transcriber.calls[0]
    assert call["existed"] and call["path"].endswith(".m4a")
    assert not os.path.exists(call["path"])


def test_transcribe_defaults_to_webm_and_reports_errors_as_json(config):
    client, _, _, transcriber = build(config, transcriber=FakeTranscriber(error=RuntimeError("bad audio")))
    response = client.post("/api/transcribe", files={"audio": ("blob", b"x", "audio/webm")})
    assert response.json() == {"text": "", "error": "bad audio"}
    assert transcriber.calls[0]["path"].endswith(".webm")
    assert not os.path.exists(transcriber.calls[0]["path"])


def test_cors_is_still_wildcard_today(config):
    # Pins CURRENT behaviour so the tightening later in Stage 0 is a deliberate, visible change.
    client, _, _, _ = build(config)
    response = client.options(
        "/api/chat",
        headers={"Origin": "https://anywhere.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"] == "*"


def test_apps_built_from_different_agents_do_not_share_data(config, tmp_path):
    client_a, agent_a, _, _ = build(config)
    other = dataclasses.replace(config, db_path=str(tmp_path / "other.db"))
    client_b, _, _, _ = build(other)
    agent_a.store.create_thread()
    assert client_b.get("/api/threads").json() == {"threads": []}
    assert len(client_a.get("/api/threads").json()["threads"]) == 1


# --- the Whisper wrapper ----------------------------------------------------------------

@pytest.fixture
def fake_whisper(monkeypatch):
    built = []

    class FakeWhisperModel:
        def __init__(self, name, device, compute_type):
            built.append((name, device, compute_type))

        def transcribe(self, path):
            return iter([types.SimpleNamespace(text=" hello "), types.SimpleNamespace(text="world ")]), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisperModel))
    return built


def test_whisper_is_loaded_lazily_and_once_with_the_same_settings_as_before(fake_whisper):
    transcriber = diya_web.WhisperTranscriber("base")
    assert fake_whisper == []
    assert transcriber.transcribe("a.wav") == "hello  world"
    transcriber.transcribe("b.wav")
    assert fake_whisper == [("base", "cpu", "int8")]


def test_whisper_warm_up_prints_the_legacy_progress_lines(fake_whisper, capsys):
    diya_web.WhisperTranscriber("small").warm_up()
    assert capsys.readouterr().out.splitlines() == ["Loading Whisper model...", "Whisper ready."]
    assert fake_whisper == [("small", "cpu", "int8")]


def test_the_default_transcriber_uses_the_configured_model(monkeypatch, fake_whisper):
    monkeypatch.setenv("DIYA_WHISPER_MODEL", "tiny")
    app = diya_web.create_app(agent=diya.Agent(client=FakeClient()))
    TestClient(app).post("/api/transcribe", files={"audio": ("c.webm", b"x", "audio/webm")})
    assert fake_whisper == [("tiny", "cpu", "int8")]


# --- main(): startup wiring ---------------------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    """Replace uvicorn.run and the real startup work; record what main() would have served."""
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(app=app, **kw))
    monkeypatch.setattr(diya, "Agent", lambda config=None: types.SimpleNamespace(config=config, warm_up=lambda: None))
    monkeypatch.setattr(diya_web, "WhisperTranscriber", lambda name: types.SimpleNamespace(name=name, warm_up=lambda: None))
    return calls


def write_mkcert_pair(folder, name="10.9.8.7+2"):
    (folder / f"{name}.pem").write_text("cert")
    (folder / f"{name}-key.pem").write_text("key")


def test_main_serves_with_config_values_and_a_discovered_mkcert_pair(served, tmp_path, monkeypatch):
    write_mkcert_pair(tmp_path, name="some-host+3")
    monkeypatch.setenv("DIYA_HOST", "127.0.0.1")
    monkeypatch.setenv("DIYA_PORT", "9443")
    diya_web.main()
    assert served["host"] == "127.0.0.1" and served["port"] == 9443
    assert os.path.basename(served["ssl_certfile"]) == "some-host+3.pem"
    assert os.path.basename(served["ssl_keyfile"]) == "some-host+3-key.pem"


def test_main_defaults_match_the_previous_hard_coded_server(served, tmp_path):
    write_mkcert_pair(tmp_path)
    diya_web.main()
    assert (served["host"], served["port"]) == ("0.0.0.0", 8080)


def test_main_prefers_an_explicit_cert_pair(served, tmp_path, monkeypatch):
    write_mkcert_pair(tmp_path)
    (tmp_path / "mine.pem").write_text("c")
    (tmp_path / "mine.key").write_text("k")
    monkeypatch.setenv("DIYA_SSL_CERT", str(tmp_path / "mine.pem"))
    monkeypatch.setenv("DIYA_SSL_KEY", str(tmp_path / "mine.key"))
    diya_web.main()
    assert served["ssl_certfile"].endswith("mine.pem") and served["ssl_keyfile"].endswith("mine.key")


def test_main_refuses_to_serve_plain_http_without_a_certificate(served, capsys):
    with pytest.raises(SystemExit) as caught:
        diya_web.main()
    assert caught.value.code == 1
    assert "no TLS certificate found" in capsys.readouterr().out
    assert "app" not in served


def test_main_reports_an_ambiguous_certificate_choice(served, tmp_path, capsys):
    write_mkcert_pair(tmp_path, "a+1")
    write_mkcert_pair(tmp_path, "b+1")
    with pytest.raises(SystemExit) as caught:
        diya_web.main()
    assert caught.value.code == 1
    assert "More than one mkcert certificate" in capsys.readouterr().out
    assert "app" not in served


def test_main_reports_a_bad_port(served, tmp_path, monkeypatch, capsys):
    write_mkcert_pair(tmp_path)
    monkeypatch.setenv("DIYA_PORT", "eighty")
    with pytest.raises(SystemExit):
        diya_web.main()
    assert "DIYA_PORT must be an integer" in capsys.readouterr().out


def test_main_fails_fast_when_ollama_is_down(run_python, tmp_path):
    write_mkcert_pair(tmp_path)
    result = run_python("import diya_web; diya_web.main()", env=DEAD_OLLAMA)
    assert result.returncode == 1
    assert "Couldn't start Diya: can't reach Ollama at" in result.stdout
    assert "Loading Whisper model" not in result.stdout  # stopped before the slow part
