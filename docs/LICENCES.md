# Licence review (2026-10-21; task DIYA-225)

The sheet asks for a review "before redistributing copied video or source research", with third-party text and image rights and notices tracked. This is that review, made by reading the package metadata and the lock
files on 2026-10-21 and the files the repository tracks. It is an engineering review, not legal advice; where a question needs a lawyer it says so.

## Diya's own licence

The repository (https://github.com/dineshyadav03/diya) is **public** and has **no LICENSE file**; GitHub shows no licence. By default that means *all rights reserved*: people may read and fork it on GitHub (GitHub's
terms allow that), and nothing else is granted. The README says the same ("All rights reserved: the code is published to read, and no licence to use, copy, modify or distribute it is granted"). Choosing a licence for Diya is the
owner's decision; until it is made, nothing here changes it. Consequence for everything below: **code taken from an AGPL or GPL project cannot be placed in Diya**, because it would oblige the whole of Diya to be offered under that licence.

## Python dependencies

`requirements.lock` pins 95 packages. Their licences, read from each package's own metadata on 2026-10-21:

| Licence family | Packages | Obligation when Diya is used or shared |
|---|---|---|
| MIT, BSD (2-clause and 3-clause), Apache-2.0, ISC, PSF-2.0, and dual "MIT or Apache-2.0" and similar | 93 | keep the notice when a package is redistributed; Diya installs them from PyPI and does not redistribute them |
| MPL-2.0 (file-level copyleft) | 2: `certifi`, and `tqdm` ("MPL-2.0 AND MIT") | only changes to the MPL-licensed *files themselves* have to be shared; Diya changes none |
| GPL, AGPL, LGPL, SSPL | **0** | none |

The packages Diya names itself (`pyproject.toml`): `fastapi` MIT, `starlette` BSD-3-Clause, `uvicorn` BSD-3-Clause, `python-multipart` Apache-2.0, `pydantic` MIT, `openai` Apache-2.0, `chromadb` Apache-2.0, `httpx` BSD-3-Clause, `ddgs` MIT,
`faster-whisper` MIT; dev: `pytest` MIT; optional extras: `cryptography` Apache-2.0 OR BSD-3-Clause, `reportlab` BSD. (`python-dateutil`'s metadata says only "Dual License": it is Apache-2.0 / BSD-3-Clause by its own documentation, which was not re-fetched today.)

## The web UI's packages

`frontend/package-lock.json` locks 55 packages besides the project itself (`next`, `react`, `react-dom` and what they pull in). Licences, from the lock file:

| Licence | Packages |
|---|---|
| MIT / Apache-2.0 / ISC / BSD-3-Clause / 0BSD | 40 |
| **LGPL-3.0-or-later** (alone, or "Apache-2.0 AND LGPL-3.0-or-later") | **14**: `@img/sharp-libvips-<platform>` (10) and `@img/sharp-<platform>` for win32 and wasm32 (4) |
| CC-BY-4.0 | 1: `caniuse-lite` (browser-support *data*, attribution required) |

**The LGPL group.** These are `sharp`'s prebuilt image-library binaries (libvips), which Next.js may use to resize images. All are *optional* dependencies: npm installs only the one for the computer's own platform. Diya's repository does not contain
them (`node_modules` is not tracked) and Diya does not ship an app bundle, so Diya does not redistribute them. LGPL asks for something only of whoever distributes the library. **If Diya is ever packaged as an installable app that includes
`node_modules`, this group needs a notice and a way for the user to replace the library; that is a decision to make then, and `tests/test_licences.py` fails if any other LGPL package appears, so it cannot arrive unnoticed.**
`caniuse-lite` is used at build time; its data is not copied into Diya's files.

## Third-party material in the repository's own files

| Item | Where | Licence and rights | Status |
|---|---|---|---|
| `mic-16.svg` and `arrow-up-16.svg` icons | `frontend/public/icons/` | MIT, Jakub Antalik (Libraries.dev); notice and licence text kept | in `THIRD_PARTY_NOTICES.md` |
| Screenshots of Diya's own pages | `docs/screenshot-*.png` | Diya's own interface; looked at today: they show an invented person ("Alex", Pune), not the owner's data | no third-party rights involved |
| `Truffle_Research_Dossier.pdf`, `RESEARCH.md` | repository root | the owner's and Diya's own writing about public products, with sources named; short quotations only | see the rule below |
| Video transcripts, the blueprint's pasted source pages, screenshots of other companies' products | **not in the repository**: they are in the owner's `Downloads` folder | third-party text and images, rights not ours | **must not be committed**; `tests/test_licences.py` fails if a tracked file carries the blueprint's page markers |

## The rule for source research that is shared or published

1. Our own words, with the source named and linked, are fine. A *short* quotation (under 15 words, one per source) with its attribution is fine.
2. Transcripts of videos, whole pages, paper text, lyrics, and screenshots of other products are **not** put in the repository, a release or a public page. They stay on the owner's own computer for the owner's own study.
3. Images and code are taken only from MIT, BSD or Apache-2.0 sources, with the author and licence named in `THIRD_PARTY_NOTICES.md` and the notice kept.
4. A source with no licence (GitHub's "NOASSERTION") or an AGPL/GPL licence is read for ideas and never copied (`docs/RESEARCH_REVIEWS_2026-10-18.md`).
5. A video the owner is shown is a reason to write down what it *claims*, in the owner's own words, and to say whether the claim was checked; not a reason to keep a copy.

## What was not reviewed

The licence of the local models Diya runs (the Qwen and Nomic models through Ollama) and of Ollama itself was not reviewed here; those are installed on the owner's computer, not distributed with Diya, and are covered by their own licences when downloaded.
Whether the all-rights-reserved choice and the public repository suit the owner's plans is a question for the owner, and for a lawyer if the project is ever sold or licensed to others.
