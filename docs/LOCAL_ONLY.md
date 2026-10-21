# What you say stays on this computer (2026-10-21; task DIYA-202)

**The rule.** Diya's default, and the owner's decision of 2026-10-18 (`docs/DECISIONS_2026-10-18.md`), is local-only AI: what you say is answered by a model running on this computer (Ollama). Nothing you say is sent to a
cloud model unless you say so, in so many words, for a reason you have in mind.

**What the code does about it.** The address of the model is one setting, `DIYA_OLLAMA_URL`, and every program of Diya's reads it from the configuration. The configuration refuses an address that is not this computer
(anything but `localhost`, `127.0.0.1`, `::1` or a name ending in `.localhost`) and says so: it names the host the words would have gone to. To send everything you say to such a host anyway, you also set
`DIYA_ALLOW_REMOTE_MODEL=1`. A pasted setting or a typo cannot do it silently. `tests/test_local_only.py` proves the check and that no program takes a model address from anywhere else.

**What it does not cover.**
* A *sensitive prompt* sent to a cloud model *case by case* (the sheet's "explicit user approval of sensitive prompt upload") is not built. Today the choice is all or nothing, made in the configuration; a per-prompt
  approval would be a new kind of approved action (tier 3 in `docs/AUTHORITY_MODEL.md`) and is not designed.
* Ollama itself, the speech and embedding models, and the web search and weather lookups. Searches and weather are outbound by design and are listed in `docs/AUTHORITY_MODEL.md`; the open accounting about them is in the Rule-of-Two section there.
* What Ollama does with its own telemetry or model downloads is Ollama's behaviour, not Diya's.
