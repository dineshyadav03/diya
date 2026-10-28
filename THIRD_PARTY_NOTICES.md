# Third-party notices

## How Diya treats other people's work

- **Nothing is copied today** except what is listed below. The code in this repository was written for Diya; none of it comes from the projects in `RESEARCH.md` (OpenClaw, Hermes Agent, Khoj, Leon,
  Hindsight, supermemory, Sentient OS and the rest). Where an idea came from one of them, the research entry says so.
- **If code from another project is ever used**, it goes in only with its licence read first, its copyright notice and licence text kept, its author and source named here and in the commit message, and
  any change of ours marked as ours. It is **never presented as written by us.** Presenting borrowed code as our own would be wrong whatever the licence, and under most licences it is also a breach of it.
- **Licences decide what is possible.** MIT, BSD and Apache-2.0 code may be reused with the notice kept (Apache-2.0 also asks that changed files say so). **AGPL-3.0 and GPL code may not be copied into
  Diya**, which is published all rights reserved: using it would oblige the whole of Diya to be offered under that licence. Sentient OS, Khoj and basic-memory are AGPL-3.0. A project with no licence, or
  one GitHub could not read, is all rights reserved by default and is not used.
- **Prefer a dependency to a copy.** A library installed from its own package keeps its own licence file and is credited by being listed in `pyproject.toml` or `frontend/package.json`.

## Libraries.dev (Jakub Antalik) — MIT

Diya's message box used to be ported from the demo chat-input mock in
[Jakubantalik/Libraries.dev](https://github.com/Jakubantalik/Libraries.dev), with six of that
author's npm packages around it. The interface was redesigned (`docs/UI_DESIGN.md`): the mock's
rules, markup and fit-to-width scaling, and the packages (`voice-glow`, `border-beam`, `liquid-gooey`,
`metal-fx`, `thinking-orbs`, `img-fx`), are gone. What remains from that source:

- `frontend/public/icons/mic-16.svg` (from `sites/home/public/assets/icons/`), used by the
  tap-to-talk button (it was hold-to-talk when this was taken).
- `frontend/public/icons/arrow-up-16.svg`, on the Send button: committed together with the composer
  and built the same way, but its source was not written down at the time, so it is treated as part
  of the same MIT-licensed set.

```
MIT License

Copyright (c) 2026 Jakub Antalik

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## DeepSeek Harness (DeepSeek AI) — MIT

The folder `harness/` is a plain copy of the files of https://github.com/deepseek-ai/deepseek-harness (commit `687f282e8625c6b8d11ff58211a90524be2e4317`, 2026-10-17), kept as received: no history, no submodule, nothing
installed, nothing built, and nothing in Diya depends on it or runs it. Its licence is `harness/LICENSE` (MIT, copyright DeepSeek AI): MIT asks that the copyright notice and the licence text stay with every copy
or substantial portion of the code, so that file is never removed. Where Diya's own code is written from it, the file says so and our changes are marked as ours.

## Atticus (SaarthurR) - MIT

Diya's shortcuts (`diya_shortcuts.py`) and its prompt budget (`tests/test_budget.py`) take their IDEAS from Atticus for macOS, https://github.com/SaarthurR/atticus-mac (version 1.5.3, read from a copy downloaded on
2026-10-28): "when I say X, do Y" that is learned once and answered at once, and a budget for what each ask may cost that tests enforce. No Atticus file is copied into this repository and none of its code is run;
Diya's versions are written for Diya's own design (the person's own words are saved, not commands, and every gate still applies). Its README says MIT ("See LICENSE"); the zip we were given had no LICENSE file,
so before any of Atticus's code is copied here, get it from the upstream repository and add its copyright line to this section. Atticus itself credits `ui/orbs.js` (thinking-orbs, MIT, Jakub Antalik) and ideas
from Plip (MIT); nothing of those is used here.

