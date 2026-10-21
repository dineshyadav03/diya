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

## DeepSeek Harness (DeepSeek AI) — MIT (study copy only; nothing is in this repository yet)

A read-only copy of https://github.com/deepseek-ai/deepseek-harness (commit `687f282e8625c6b8d11ff58211a90524be2e4317`, 2026-10-17) is kept **outside** this repository, at `C:\Users\dines\dsh-copy\deepseek-harness`, for study (`docs/DSH_PLAN.md`).
No file from it is part of Diya yet. When any code is taken, its copyright notice and the MIT licence text come here with it, the file says where it came from, and our changes are marked as ours.
