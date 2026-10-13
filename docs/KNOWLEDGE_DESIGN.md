# A knowledge base from your own notes (unit K1, step 1)

> **Status (2026-10-13):** step 1 built (`diya_knowledge.py`, `DIYA_KNOWLEDGE_DIR`, `python diya_knowledge.py build`), and the **Knowledge page** to read, build and hide pages in the UI (`diya_knowledge_api.py`,
> `frontend/app/knowledge/`). Not built: the chat reading a page, and a second source.
> Unit K1 of `docs/RESEARCH_PLAN_2026-10.md`; the research is `RESEARCH.md` entries 29 and 31.

## What it is for

`search_notes` embeds each file of one folder and returns the single closest file. "What do my notes say about Maya?" gets one note, not everything written about her. K1 gives each recurring name (a person,
a project, a place) a **page** that collects every sentence the notes say about it, with where each came from, and links to the other names that appear beside it. It is the shape Sentient OS and Cognition's
"agent memory repo" use (entries 21 and 29): ordinary Markdown files in one folder that you can open, read and edit with any editor, including Obsidian.

## The decision that shapes everything: pages are made by code, from your own words

Pages are **not written by the model.** Each page holds only *sentences copied word for word from your notes*, grouped under the name they mention. The model has no part in step 1: no extraction call, no summary.

- Nothing can be invented. A summary by a 4B model could say something your notes never said; a copied sentence cannot. The only thing Diya "infers" is *which sentences belong under which name*, and
  that is a plain rule you can read.
- It follows `docs/GATE_BENCHMARK.md` (the code decides, the model is worse at it) and the research (CorpusMap builds its entity map without a model, entry 31).
- It costs no CPU time and works with Ollama switched off, so it can run any time, not only at night.
- A model may help later with the two things code cannot do (that "my sister" and "Maya" are one person; a one-line summary marked as a summary). That is only added if a measurement says it earns its keep.

## What it does

`python diya_knowledge.py build` reads the notes folder (`DIYA_NOTES_DIR`) and writes the knowledge folder (`DIYA_KNOWLEDGE_DIR`, default `knowledge/`). Reading is **read-only**: it never changes a note.

1. **Reading.** `.txt`, `.md` and `.markdown` files, in sub-folders too (up to four deep), skipping hidden folders (`.obsidian`, `.git`), files over 200 KB, anything that is not inside the notes folder
   (a link out of it is not followed), and anything Diya itself generated. At most 5,000 files. A leading `---` front-matter block and fenced code blocks are left out.
2. **Units.** Each note is cut into sentences (a bullet or a line is one too), at most 300 characters.
3. **Names.** A name gets a page when it is
   - written as a `[[wiki link]]` or an `@mention` (you marked it yourself), or
   - one of the people Diya already knows about (the `people` table of the Memory page), or
   - a capitalised word or phrase that appears in **two or more different notes** (the recurring-entity idea of CorpusMap) and is written with a capital **somewhere that is not the start of a sentence**
     (a sentence starts with a capital whatever the word is, so "Need milk" in two notes makes no page, and "Call Maya" and "Ask Maya" make one for Maya, not for "Call Maya"). A word the notes write in
     lowercase more often than with a capital in mid-sentence ("call", "rose") is an ordinary word, not a name. A title stays with its name ("Dr Mehta"). Days, months and common words never count.
4. **Pages.** One page per name, `Name.md`: the sentences (newest note first, at most 40), each with the note it is from; and "Mentioned with", links to other pages whose names appear in the same sentences.
   Links are `[[Name]]`, so Obsidian shows the graph. `index.md` lists every page.
5. **Re-running.** Pages are rewritten only when their content changed; a page whose name no longer qualifies is removed *if Diya generated it*. A file that does not start with Diya's marker line is
   yours and is never overwritten or deleted (a name that would collide with one is skipped and reported).
6. **Hiding.** `python diya_knowledge.py hide "Name"` removes the page and keeps it from coming back (the name goes in `knowledge/hidden.txt`, a plain file you can also edit); `unhide "Name"` undoes it.
   Every page says so at the top.

## What it must never do

- **Nothing here becomes a fact.** Pages are a separate folder, never read into Memory, never told to the model in step 1. (Cross-cutting note 8: what a background job infers is shown, never accepted.)
- **A note cannot give an order.** Note text is only ever copied into a page as text. It is not sent to a model, and nothing is run or fetched because of it. When a later step lets the chat read pages, they
  are read as data, as web results are (`docs/LOOKUP_DESIGN.md`).
- **It cannot write outside its folder.** A page's file name is made from the name by allowing letters, digits, spaces and a few marks; `[[../../x]]` becomes nothing. The knowledge folder must not be
  inside the notes folder (or Diya would read its own pages back as notes).
- **Personal data stays out of git.** `knowledge/` is in `.gitignore`: once your own notes are in it, it is personal data like `diya.db`.

## Measured

Two invented sets of notes (written by me, with my own list of which names should get a page). The title rule and the lowercase rule were added after the first runs showed those gaps, so the numbers are
for the final rules on the same sets, **not a blind test**.

- **Set 1, 24 notes of an invented life** (people, a pet, places, projects, and traps: sentence starters, days, months, title-case headings, names that appear once): **13 of 13** recurring names got a
  page, and **none** of the traps did (Need, Call, Remember, Thanks, Gym, September, the one-off Anand, Kerala and Zomato, a title-case heading). The 69 sentences on the pages were all found word for
  word in the note each names, and none that mentions a page's name was missing from it. The question "what do my notes say about X?" is reached by a page in every note that mentions X; `search_notes`
  returns one note, which was one of the notes that mention the name, averaging **23%** of them over the 13 names (Maya is in 8 notes; search returned 1). Building took under a tenth of a second.
- **Set 2, 8 sloppy notes** (names typed in lowercase, names at the start of sentences): **4 of 5** names with nothing marked and no one known (Kavya was only ever at a sentence start or in lowercase),
  **5 of 5** once the people Diya already knows were given.

**Not measured:** real notes (the notes folder holds six one-line demo notes), notes that are not in English, a folder of thousands of notes (the limits are 5,000 files and 50 MB), and whether you find the
pages useful: that is the real test, and it starts when `DIYA_NOTES_DIR` points at a folder of yours.

## Limits, plainly

- **It finds names by their capital letter.** Notes written all in lowercase give only the people Diya already knows and the `[[links]]` you wrote; a name that only ever starts sentences needs the same.
- **"Maya" and "Maya Rao" are two pages**, and "my sister" is no page. Joining them is the job of a later model step or of you (hide one).
- **A sentence under a name is not always about it.** Any sentence that contains the name goes on its page: "Sam knows someone at the embassy" is on Japan's page if it also says "Japan". The page shows the
  whole sentence and where it is from, so it is visible; it is never reworded.
- **A name that is also an ordinary word** (Will, May) is never found by itself, because the word is too common; write it as `[[Will]]` and it is.
- **The demo notes in `sample_notes/` are six one-line notes**, so they produce almost nothing. The mechanism is measured on invented notes; to use it on your own, point `DIYA_NOTES_DIR` at a folder you choose. Diya
  does not look anywhere you have not pointed it.

## Next steps (not built)

2. **Built:** a **Knowledge page** in the UI (sidebar, under Memory): the notes folder in use, a "Read my notes now" button, the names that have a page, a page with each sentence and the note it came from, links to
   the names beside it, "Hide this name", and the hidden names with "Bring back". Routes: `GET /api/knowledge`, `POST /api/knowledge/build`, `/hide`, `/unhide`; the same token rule as every route.
   **Not built:** the chat reading a page when you ask "what do my notes say about X?". That is the step that needs care: a page is text from your notes, so the chat has to read it as data, as it reads web results.
3. A **second source**, one at a time and only if you want it: Calendar once connected; mail and messages only by your decision.
