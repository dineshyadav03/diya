"""Replies that appear as they are written, the orbs' microphone, and the pieces of the page that read them (docs/STREAMING_DESIGN.md): diya.py's `on_event`, POST /api/chat/stream,
frontend/lib/chat-stream.mjs and frontend/lib/microphone.mjs (the last two run under Node, as the other front-end helpers are).

What this proves: a streamed reply is told word by word and is, joined, exactly the answer that comes back; a tool round says which tool and takes back any preface; a fact-share is told whole
(it is shortened afterwards); the route's lines are start, delta..., done with exactly what /api/chat returns, or error with the reason and the chat the message was kept in; the page's reader
copes with a line split across chunks, with an error and with a stream that just stops; and the microphone tries the default, then each real microphone, never retries a refusal, and says
what to do in each case.
"""
import dataclasses
import json
import pathlib
import shutil
import subprocess

import openai
import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from fakes import FakeClient, text_reply, tool_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "s.db"), profile_path=str(tmp_path / "profile.txt"), require_token=False)


def make_agent(config, replies, **kwargs):
    return diya.Agent(config, client=FakeClient(list(replies), **kwargs))


def collect(agent, history, **kwargs):
    events = []
    answer, tools = agent.ask(history, on_event=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return answer, tools, events


# ---- the agent ---------------------------------------------------------------------------------------------------------------

def test_a_reply_is_told_a_word_at_a_time_and_joined_it_is_the_answer(config):
    agent = make_agent(config, [text_reply("Hey Alex, how is your day going?")])
    answer, tools, events = collect(agent, [{"role": "user", "content": "what time is it in Tokyo"}])
    assert [k for k, _ in events] == ["delta"] * 7 and "".join(p for _, p in events) == answer == "Hey Alex, how is your day going?" and tools == []
    assert agent.client.chat_calls[0]["options"] == {"stream": True}


def test_without_on_event_nothing_is_streamed_as_before(config):
    agent = make_agent(config, [text_reply("Plain.")])
    assert agent.ask([{"role": "user", "content": "what time is it in Tokyo"}]) == ("Plain.", [])
    assert agent.client.chat_calls[0]["options"] == {}


def test_a_tool_round_says_which_tool_and_the_reply_after_it_is_what_is_told(config):
    agent = make_agent(config, [tool_reply("list_reminders"), text_reply("You have nothing due.")])
    answer, tools, events = collect(agent, [{"role": "user", "content": "what is on my list"}])
    assert tools == ["list_reminders"] and [e for e in events if e[0] != "delta"] == [("tool", "list_reminders")]
    assert "".join(p for k, p in events if k == "delta") == answer == "You have nothing due."
    second = agent.client.chat_calls[1]["messages"]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"][0]["function"] == {"name": "list_reminders", "arguments": "{}"}  # put back as a plain dict
    assert second[-1]["role"] == "tool"


def test_text_that_came_before_a_tool_call_is_taken_back(config):
    from types import SimpleNamespace

    both = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Let me look. ", tool_calls=tool_reply("list_reminders").choices[0].message.tool_calls))])
    agent = make_agent(config, [both, text_reply("Nothing due.")])
    answer, _, events = collect(agent, [{"role": "user", "content": "what is on my list"}])
    kinds = [k for k, _ in events]
    assert kinds.index("reset") > kinds.index("delta") and kinds.index("reset") < kinds.index("tool") and answer == "Nothing due."


def test_a_tool_call_whose_arguments_arrive_in_pieces_is_put_together(config):
    agent = make_agent(config, [tool_reply("get_weather", '{"city": "Pune", "units": "metric"}'), text_reply("Warm.")])
    collect(agent, [{"role": "user", "content": "weather in Pune"}])
    assert agent.client.chat_calls[1]["messages"][-2]["tool_calls"][0]["function"]["arguments"] == '{"city": "Pune", "units": "metric"}'


def test_a_fact_share_is_told_whole_because_it_is_shortened_afterwards(config):
    agent = make_agent(config, [text_reply("Got it, your flight is on Friday at 6. Have a lovely trip! I hope it goes well and that you enjoy every minute of it, truly.")])
    answer, _, events = collect(agent, [{"role": "user", "content": "my flight is on Friday at 6pm"}])
    assert events == [] and agent.client.chat_calls[0]["options"] == {} and answer.startswith("Got it")


def test_a_model_that_says_nothing_is_asked_once_more_and_that_is_told_too(config):
    agent = make_agent(config, [text_reply(""), text_reply("Here now.")])
    answer, _, events = collect(agent, [{"role": "user", "content": "what time is it in Tokyo"}])
    assert answer == "Here now." and "".join(p for k, p in events if k == "delta") == "Here now." and len(agent.client.chat_calls) == 2


def test_a_greeting_streams_with_its_looser_temperature_and_no_tools(config):
    agent = make_agent(config, [text_reply("Hey!")])
    collect(agent, [{"role": "user", "content": "hey"}])
    call = agent.client.chat_calls[0]
    assert call["tools"] is None and call["options"] == {"temperature": diya.SMALL_TALK_TEMPERATURE, "stream": True}


# ---- the route ---------------------------------------------------------------------------------------------------------------

def lines_of(response):
    return [json.loads(line) for line in response.iter_lines() if line]


def stream(client, **body):
    with client.stream("POST", "/api/chat/stream", json=body) as response:
        assert response.headers["content-type"].startswith("application/x-ndjson") and response.headers["cache-control"] == "no-store"
        return response.status_code, lines_of(response)


def test_the_route_tells_start_then_the_words_then_exactly_what_the_chat_route_returns(config):
    agent = make_agent(config, [text_reply("It is warm today.")])
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    status, events = stream(client, message="what is the weather like")
    assert status == 200 and events[0] == {"type": "start", "thread_id": 1, "message_id": 1}
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "It is warm today."
    assert events[-1] == {"type": "done", "thread_id": 1, "answer": "It is warm today.", "tools_called": [], "message_id": 1, "reading": False}
    assert agent.store.get_history(1) == [{"role": "user", "content": "what is the weather like"}, {"role": "assistant", "content": "It is warm today."}]


def test_the_route_and_the_plain_chat_route_agree_on_everything_but_the_telling(config):
    plain = TestClient(diya_web.create_app(config, make_agent(config, [text_reply("Same words.")]), object()), base_url="https://localhost").post("/api/chat", json={"message": "tell me something"}).json()
    other = dataclasses.replace(config, db_path=config.db_path + "2")
    streamed = stream(TestClient(diya_web.create_app(other, make_agent(other, [text_reply("Same words.")]), object()), base_url="https://localhost"), message="tell me something")[1][-1]
    assert {k: v for k, v in streamed.items() if k != "type"} == plain


def test_a_model_that_cannot_answer_is_an_error_line_with_the_reason_and_the_chat_the_message_was_kept_in(config):
    agent = make_agent(config, [], chat_error=openai.APIConnectionError(request=None))
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    status, events = stream(client, message="what time is it")
    assert status == 200 and events[-1] == {"type": "error", "status": 503, "detail": diya_web.MODEL_DID_NOT_ANSWER, "thread_id": 1}
    assert agent.store.get_history(1) == [{"role": "user", "content": "what time is it"}]  # kept, and nothing pretends to be a reply


def test_a_defect_is_a_500_error_line_in_fixed_words_without_its_text(config):
    agent = make_agent(config, [], chat_error=RuntimeError("SECRET-DETAIL"))
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    _, events = stream(client, message="what time is it")
    assert events[-1] == {"type": "error", "status": 500, "detail": diya_web.ANSWERING_FAILED, "thread_id": 1} and "SECRET-DETAIL" not in json.dumps(events)


def test_trying_again_after_a_failed_streamed_turn_does_not_save_the_message_twice(config):
    agent = make_agent(config, [], chat_error=RuntimeError("down"))
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    stream(client, message="what time is it")
    agent.client.replies.append(text_reply("Noon."))
    agent.client._chat_error = None
    _, events = stream(client, thread_id=1, message="what time is it")
    assert events[-1]["answer"] == "Noon." and [m["content"] for m in agent.store.get_history(1)] == ["what time is it", "Noon."]


def test_a_turn_that_is_slow_says_it_is_still_working(config, monkeypatch):
    import threading

    release = threading.Event()
    agent = make_agent(config, [text_reply("Finally.")])
    original = agent.ask

    def slow(*a, **k):
        release.wait(5)
        return original(*a, **k)

    agent.ask = slow
    monkeypatch.setattr(diya_web, "STREAM_PING_SECONDS", 0.05)
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    with client.stream("POST", "/api/chat/stream", json={"message": "what time is it"}) as response:
        seen = []
        for line in response.iter_lines():
            if not line:
                continue
            seen.append(json.loads(line)["type"])
            if seen.count("wait") == 2:
                release.set()
    assert seen[0] == "start" and seen.count("wait") >= 2 and seen[-1] == "done"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")  # the worker dies on purpose
def test_a_turn_that_dies_without_a_word_does_not_leave_the_page_waiting(config, monkeypatch):
    agent = make_agent(config, [])

    def dies(*a, **k):
        raise SystemExit  # not an Exception: the worker ends without telling anyone

    agent.ask = dies
    monkeypatch.setattr(diya_web, "STREAM_PING_SECONDS", 0.05)
    client = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")
    _, events = stream(client, message="what time is it")
    assert events[-1]["type"] == "error" and events[-1]["detail"] == diya_web.ANSWERING_FAILED


# ---- the page's reader (Node) --------------------------------------------------------------------------------------------------

def node(script):
    done = subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


READ = """
import { readChatStream } from './lib/chat-stream.mjs'
const encoder = new TextEncoder()
function bodyOf(chunks) { let i = 0; return { getReader: () => ({ read: async () => i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { value: undefined, done: true } }) } }
const seen = []
const handlers = { onStart: (e) => seen.push(['start', e.thread_id]), onDelta: (t) => seen.push(['delta', t]), onReset: () => seen.push(['reset']), onTool: (e) => seen.push(['tool', e.name]), onWait: () => seen.push(['wait']), onError: (e) => seen.push(['error', e.status, e.detail]) }
let outcome
try { outcome = { done: await readChatStream(bodyOf(CHUNKS), handlers) } } catch (error) { outcome = { threw: error.message } }
console.log(JSON.stringify({ seen, outcome }))
"""


@needs_node
def test_the_reader_joins_a_line_split_across_chunks_and_returns_the_done_event():
    chunks = ['{"type":"start","thread_id":7}\n{"type":"del', 'ta","text":"Hey "}\n{"type":"delta","text":"Alex"}\n{"type":"wait"}\n{"type":"tool","name":"x"}\n{"type":"reset"}\n', '{"type":"done","answer":"Hey Alex","thread_id":7}']
    result = node(READ.replace("CHUNKS", json.dumps(chunks)))
    assert result["seen"] == [["start", 7], ["delta", "Hey "], ["delta", "Alex"], ["wait"], ["tool", "x"], ["reset"]] and result["outcome"] == {"done": {"type": "done", "answer": "Hey Alex", "thread_id": 7}}


@needs_node
def test_the_reader_throws_on_an_error_line_after_telling_the_caller_why():
    result = node(READ.replace("CHUNKS", json.dumps(['{"type":"start","thread_id":7}\n{"type":"error","status":503,"detail":"no model","thread_id":7}\n'])))
    assert result["seen"][-1] == ["error", 503, "no model"] and result["outcome"] == {"threw": "chat stream failed"}


@needs_node
@pytest.mark.parametrize("chunks", [[], ['{"type":"start","thread_id":7}\n{"type":"delta","text":"half a rep'], ['not json at all\n'], ['[1,2]\n'], ['"text"\n']])
def test_the_reader_throws_when_the_stream_stops_short_or_is_not_what_it_expects(chunks):
    result = node(READ.replace("CHUNKS", json.dumps(chunks)))
    assert result["outcome"] == {"threw": "chat stream failed"} and result["seen"][-1][0] == "error" and result["seen"][-1][1] is None


@needs_node
def test_the_reader_ignores_blank_lines_and_unknown_kinds_and_a_delta_with_no_text():
    chunks = ['\n\n{"type":"mystery"}\n{"type":"delta"}\n{"type":"delta","text":5}\n{"type":"done","answer":"x"}\n']
    result = node(READ.replace("CHUNKS", json.dumps(chunks)))
    assert result["seen"] == [] and result["outcome"] == {"done": {"type": "done", "answer": "x"}}


# ---- the microphone (Node) -----------------------------------------------------------------------------------------------------

MIC = """
import { describeMicrophoneFailure, forgetSilent, markSilent, markWorking, openMicrophone } from './lib/microphone.mjs'
const store = {}
globalThis.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v) }, removeItem: (k) => { delete store[k] } }
const fail = (name) => Object.assign(new Error(name), { name })
function media({ works = [], devices = [] }, groupsOf) {
  const asked = []
  const groups = groupsOf || {}
  const stream = (id, group) => ({ id, stopped: false, getTracks() { return [{ stop: () => { this.stopped = true } }] }, getAudioTracks() { return [{ label: 'Mic ' + id, getSettings: () => ({ deviceId: id, groupId: group || '' }) }] } })
  return { asked, getUserMedia: async (c) => { const id = c.audio === true ? 'default' : c.audio.deviceId.exact; asked.push(id); if (works.includes(id)) return stream(id, c.audio === true ? (groups.default || '') : (groups[id] || '')); throw fail(works.error || 'NotReadableError') },
           enumerateDevices: async () => devices.map((id) => ({ kind: id.startsWith('out') ? 'audiooutput' : 'audioinput', deviceId: id, groupId: groups[id] || '' })) }
}
const run = async (m) => { try { return { got: (await openMicrophone(m)).id } } catch (e) { return { threw: e.name } } }
const open = async (m) => { try { return await openMicrophone(m) } catch (e) { return { threw: e.name } } }
const asked = async (m) => { const r = await open(m); return r.id ?? r.threw }
const out = {}
SCRIPT
console.log(JSON.stringify({ out, store }))
"""


def mic(script):
    return node(MIC.replace("SCRIPT", script))


@needs_node
def test_the_default_microphone_is_used_when_it_works_and_nothing_else_is_asked():
    result = mic("const m = media({ works: ['default'], devices: ['a'] }); out.r = await run(m); out.asked = m.asked")
    assert result["out"] == {"r": {"got": "default"}, "asked": ["default"]} and result["store"] == {}


@needs_node
def test_when_the_default_will_not_start_each_real_microphone_is_tried_and_the_first_that_works_is_remembered():
    result = mic("const m = media({ works: ['c'], devices: ['default', 'communications', 'out1', 'a', 'b', 'c', 'd'] }); out.r = await run(m); out.asked = m.asked")
    assert result["out"] == {"r": {"got": "c"}, "asked": ["default", "a", "b", "c"]} and result["store"] == {"diya_mic_device": "c"}


@needs_node
def test_the_remembered_microphone_is_tried_first_and_forgotten_when_it_stops_working():
    result = mic("store.diya_mic_device = 'old'; const m = media({ works: ['default'] }); out.r = await run(m); out.asked = m.asked; out.after = store.diya_mic_device ?? null")
    assert result["out"] == {"r": {"got": "default"}, "asked": ["old", "default"], "after": "old"}  # the plain default worked, so the old one is only forgotten if nothing worked
    result = mic("store.diya_mic_device = 'old'; const m = media({ works: [], devices: ['a'] }); out.r = await run(m); out.after = store.diya_mic_device ?? null")
    assert result["out"] == {"r": {"threw": "NotReadableError"}, "after": None}


@needs_node
def test_a_refusal_is_never_retried_with_another_device():
    result = mic("const m = media({ works: Object.assign([], { error: 'NotAllowedError' }), devices: ['a', 'b'] }); out.r = await run(m); out.asked = m.asked")
    assert result["out"] == {"r": {"threw": "NotAllowedError"}, "asked": ["default"]}


@needs_node
def test_no_media_devices_at_all_is_the_not_a_secure_address_case():
    result = mic("out.a = await run(undefined); out.b = await run({})")
    assert result["out"] == {"a": {"threw": "InsecureContext"}, "b": {"threw": "InsecureContext"}}


@needs_node
def test_every_failure_says_what_to_do_and_names_the_problem_it_does_not_know():
    result = mic("for (const n of ['InsecureContext','NotAllowedError','SecurityError','NotFoundError','OverconstrainedError','NotReadableError','AbortError','TypeError','']) out[n || 'none'] = describeMicrophoneFailure({ name: n }); out.nothing = describeMicrophoneFailure(undefined)")["out"]
    assert "https://localhost:3000" in result["InsecureContext"] and "Allow" in result["NotAllowedError"] and result["NotAllowedError"] == result["SecurityError"]
    assert "no microphone was found" in result["NotFoundError"] and result["NotFoundError"] == result["OverconstrainedError"]
    assert "another app" in result["NotReadableError"] and "headset" in result["NotReadableError"] and result["NotReadableError"] == result["AbortError"]
    assert "(TypeError)" in result["TypeError"] and "(unknown problem)" in result["none"] and "(unknown problem)" in result["nothing"]
    assert all(text.startswith("Microphone: ") for text in result.values())


@needs_node
def test_a_microphone_heard_to_be_silent_is_not_offered_again_so_each_silent_try_moves_on_to_the_next():
    script = """
    const m = media({ works: ['default', 'a', 'b'], devices: ['default', 'a', 'b'] })
    const first = await open(m); out.first = first.id; markSilent(first)
    const second = await open(m); out.second = second.id; markSilent(second)
    out.third = await asked(m)
    out.askedAll = m.asked
    """
    result = mic(script)["out"]
    assert result["first"] == "default" and result["second"] == "a" and result["third"] == "b" and result["askedAll"] == ["default", "a", "b"]


@needs_node
def test_the_same_physical_microphone_under_another_id_is_skipped_too():
    script = """
    const m = media({ works: ['default', 'a', 'b'], devices: ['default', 'a', 'b'] }, { default: 'g1', a: 'g1', b: 'g2' })
    const first = await open(m); markSilent(first)
    out.next = await asked(m)
    out.askedAll = m.asked
    """
    result = mic(script)["out"]
    assert result["next"] == "b" and result["askedAll"] == ["default", "b"]  # a is the default's own microphone (the same group), so it is not tried


@needs_node
def test_when_every_microphone_has_been_heard_silent_it_says_so_once_and_starts_over():
    script = """
    const m = media({ works: ['default', 'a'], devices: ['default', 'a'] })
    for (const expected of ['default', 'a']) { const r = await open(m); out['got_' + expected] = r.id; markSilent(r) }
    out.none = await asked(m)
    out.after = await asked(m)
    """
    result = mic(script)["out"]
    assert result == {"got_default": "default", "got_a": "a", "none": "NoSoundAnywhere", "after": "default"}


@needs_node
def test_a_microphone_that_picked_up_sound_is_remembered_unless_it_is_just_the_default():
    result = mic("const m = media({ works: ['a'], devices: ['a'] }); const r = await open(m); markWorking(r); out.saved = store.diya_mic_device ?? null")
    assert result["out"] == {"saved": "a"}
    result = mic("const m = media({ works: ['default'], devices: [] }); const r = await open(m); markWorking(r); out.saved = store.diya_mic_device ?? null")
    assert result["out"] == {"saved": None}


@needs_node
def test_a_remembered_microphone_that_goes_silent_is_forgotten():
    script = """
    store.diya_mic_device = 'a'
    const m = media({ works: ['a', 'default'], devices: ['a'] })
    const r = await open(m); out.got = r.id; markSilent(r)
    out.saved = store.diya_mic_device ?? null
    out.next = await asked(m)
    """
    result = mic(script)["out"]
    assert result == {"got": "a", "saved": None, "next": "default"}


@needs_node
def test_the_no_sound_failure_says_what_to_do():
    text = mic("out.t = describeMicrophoneFailure({ name: 'NoSoundAnywhere' })")["out"]["t"]
    assert text.startswith("Microphone: none of the microphones") and "Settings" in text and "bar move" in text


# ---- what is checked in ------------------------------------------------------------------------------------------------------

def test_the_page_never_shows_a_streamed_reply_that_did_not_finish_and_asks_for_the_stream_first():
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert page.index("fetch('/api/chat/stream'") < page.index("fetch('/api/chat'") and "res.status === 404" in page
    assert page.count("setStreamText('')") >= 3 and "streamText && <div className=\"msg assistant streaming\">" in page
    assert "(thinking && !streamText) || speaking" in page and "<Orb state=" in page


def test_the_microphone_button_is_tap_to_start_and_tap_again_to_send_and_nothing_is_held():
    voice = (ROOT / "frontend" / "components" / "VoiceBar.jsx").read_text(encoding="utf-8")
    assert "onClick={() => (recording ? stopRecording() : startRecording())}" in voice and "aria-pressed={recording}" in voice
    assert "aria-label={recording ? 'Tap to stop and send' : 'Tap to talk'}" in voice
    assert not any(handler in voice for handler in ("onPointerDown", "onPointerUp", "onPointerLeave", "onPointerCancel", "setPointerCapture", "Hold to talk", "Hold the mic"))
    assert "<Orb state={recording ? 'listening' : 'thinking'}" in voice and "recorded ${kb} KB" not in voice


def test_a_recording_with_no_sound_is_never_sent_and_the_next_tap_uses_another_microphone():
    voice = (ROOT / "frontend" / "components" / "VoiceBar.jsx").read_text(encoding="utf-8")
    silent_at, send_at = voice.index("peakRef.current < SILENT_BELOW"), voice.index("fetch('/api/transcribe'")
    assert silent_at < send_at and voice.index("markSilent(mic)") < send_at and "return" in voice[silent_at:voice.index("markWorking(mic)")]
    assert "MIN_RECORDING_MS" in voice and "MAX_RECORDING_MS" in voice and "setTimeout(() => stopRecording(), MAX_RECORDING_MS)" in voice
    assert "stopRecording(true)" in voice and "Cancel" in voice and "discardRef" in voice  # Cancel throws the recording away
    assert voice.count("mediaRecorder.stream.getTracks().forEach((t) => t.stop())") == 2  # stopping, and leaving the page, both let go of the microphone


def test_the_orb_is_only_css_and_stops_under_reduced_motion():
    css = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")
    assert ".orb-core" in css and "@keyframes orb-spin" in css and "@media (prefers-reduced-motion: reduce)" in css and "animation-iteration-count: 1 !important" in css
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert "thinking-orbs" not in package["dependencies"] and "voice-glow" not in package["dependencies"]
