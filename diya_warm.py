"""Keep the chat model loaded, so the first message after a pause is not slow (docs/SPEED_DESIGN.md).

Measured on this computer (CPU only): the first message after the model had been idle took about 20 seconds ("hey" included): about 7 of them loading the model, and about 13 reading the
~1,000 tokens of the system message and the eight tools' descriptions; the same message with the model loaded and that part already read took about 3. Ollama unloads a model after five idle
minutes by default, which is why every message after a coffee was the slow kind. This does two things while the API runs:

    prime()   once, at start: load the model and read exactly the system message and tools a chat sends, so the first real message finds them cached
    renew()   every few minutes: tell Ollama to keep the model for a while longer (a request with no prompt: it loads nothing and generates nothing, it only moves the unload time)

Nothing here reads anything of the person's except what every chat already sends the model, and nothing leaves this computer: the requests go to the Ollama address in the settings. It is on by
default and `DIYA_KEEP_WARM=0` turns it off (the cost of leaving it on is the model's memory, about 3 GB for the 4B model, held for as long as the API runs).
"""
from __future__ import annotations

import threading

from diya_memory import printable

RENEW_SECONDS = 240.0  # well inside Ollama's own five minutes, and the keep-alive below is much longer than this
REQUEST_TIMEOUT = 600.0  # the first load of a model, on a CPU, can take a minute or two


def native_address(ollama_url):
    """The address of Ollama's own API from the OpenAI-style address the chat uses ("http://localhost:11434/v1" becomes "http://localhost:11434")."""
    base = ollama_url.rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


def post_json(url, payload, timeout):
    """POST `payload` as JSON; True if Ollama answered with a success. Never raises: Ollama not running is not this program's failure."""
    import httpx

    try:
        return httpx.post(url, json=payload, timeout=timeout).status_code == 200
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return False


class KeepWarm:
    """`post(url, payload, timeout)` returns True when Ollama accepted the request; `sleep` and `say` are passed in so a test can stand in for time and for the console."""

    def __init__(self, config, agent=None, post=post_json, sleep=None, say=print):
        self.config, self.agent, self._post, self._sleep, self.say = config, agent, post, sleep, say
        self._stop = threading.Event()
        self._was_up = None
        self.thread = None
        self._primed = None  # the start of the system message that was read when priming: when it changes (a new fact, a new day) it has to be read again

    def _prefix(self):
        """The system message a chat starts with right now, or None if there is none or it cannot be built."""
        try:
            return self.agent.with_profile([])[0]["content"]
        except Exception:  # noqa: BLE001
            return None

    def _wait(self, seconds):
        """Wait, ending early if stopped; a test passes `sleep` to stand in for time."""
        if self._sleep is not None:
            self._sleep(seconds)
        else:
            self._stop.wait(seconds)

    def _generate_url(self):
        return native_address(self.config.ollama_url) + "/api/generate"

    def renew(self):
        """Ask Ollama to keep the chat model for `keep_alive` longer, loading it if it is not loaded. Returns True if Ollama answered. Said once when that changes, never repeated."""
        up = bool(self._post(self._generate_url(), {"model": self.config.model, "keep_alive": self.config.keep_alive, "stream": False}, REQUEST_TIMEOUT))
        if up != self._was_up:
            if up:
                self.say(f"The model ({printable(self.config.model, 80)}) is loaded and will be kept loaded while this runs.")
            elif self._was_up is not None:
                self.say("Ollama is not answering, so the model may unload; trying again in a few minutes.")
            self._was_up = up
        return up

    def prime(self):
        """Read the system message and the tools a chat sends, now, so the first real message does not pay for them. Returns True if it was done. Any failure is a no, not an error:
        the chat works without it, only slower."""
        if self.agent is None:
            return False
        try:
            history = self.agent.with_profile([{"role": "user", "content": "hello"}])
            self.agent.client.chat.completions.create(
                model=self.config.model, messages=self.agent._model_messages(history, False), tools=self.agent.tools, max_tokens=1)
            self._primed = self._prefix()
            return True
        except Exception:  # noqa: BLE001 -- warming is a courtesy; the real chat reports its own failures
            return False

    def run(self):
        """Load the model and prime it, then renew it every RENEW_SECONDS until stopped."""
        if self.renew():
            self.prime()
        while not self._stop.is_set():
            self._wait(RENEW_SECONDS)
            if self._stop.is_set():
                break
            if self.renew() and self._prefix() != self._primed:  # a new fact or a new day changes the start of every message: read it now, not in the middle of the next one
                self.prime()

    def start(self):
        """Run in a background thread that never keeps the program alive. Returns the thread."""
        self.thread = threading.Thread(target=self.run, name="keep-warm", daemon=True)
        self.thread.start()
        return self.thread

    def stop(self):
        self._stop.set()
