"""The pages made from your notes, over HTTP (docs/KNOWLEDGE_DESIGN.md, K1 step 2): the routes behind the UI's Knowledge page.

    GET  /api/knowledge            {"notes_folder", "demo", "built", "pages": [{stem, name, sentences: [{text, source}], omitted, notes, links}], "hidden": [name]}
    POST /api/knowledge/build      read the notes folder now and write the pages (it only reads the notes, uses no model and no network); answers what it did and the list
    POST /api/knowledge/hide       {"name": "Maya"}  remove that name's page and never make it again
    POST /api/knowledge/unhide     {"name": "Maya"}  make it again from the next build

Every route is behind the access token like the rest of the API. A refusal is an HTTP error with the reason in `detail`: 409 when a build cannot run (no such notes folder, one already running),
422 for a name that cannot have a page. Everything sent back goes through diya_memory.printable(): a page is built from the person's notes, which anyone may have written into.
"""
from __future__ import annotations

import os
import threading

from fastapi import HTTPException
from pydantic import BaseModel, Field

import diya_knowledge
from diya_memory import printable

DEMO_FOLDER = "sample_notes"
MAX_NAME = 200


class NameBody(BaseModel):
    name: str = Field(max_length=MAX_NAME)


def register(app, config, agent):
    """Add the routes to `app`, directly, like every other route. Nothing is read or written here: registering is free."""
    building = threading.Lock()

    def listing():
        out = config.knowledge_dir
        pages = []
        for stem in diya_knowledge.list_pages(out)[0]:
            page = diya_knowledge.read_page(out, stem)
            if page is None:
                continue
            pages.append({
                "stem": printable(page["stem"]),
                "name": printable(page["name"], diya_knowledge.NAME_CHARS),
                "sentences": [{"text": printable(item["text"]), "source": printable(item["source"])} for item in page["sentences"]],
                "omitted": page["omitted"],
                "notes": len({item["source"] for item in page["sentences"]}),
                "links": [printable(link, diya_knowledge.NAME_CHARS) for link in page["links"]],
            })
        pages.sort(key=lambda p: (-(len(p["sentences"]) + p["omitted"]), p["name"].casefold()))
        return {
            "notes_folder": printable(config.notes_dir),
            "demo": os.path.basename(os.path.normpath(config.notes_dir)) == DEMO_FOLDER,
            "built": os.path.isfile(os.path.join(out, diya_knowledge.INDEX_STEM + ".md")),
            "pages": pages,
            "hidden": [printable(name) for name in diya_knowledge.list_pages(out)[1]],
        }

    @app.get("/api/knowledge")
    def knowledge():
        return listing()

    @app.post("/api/knowledge/build")
    def build():
        if not building.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="a build is already running")
        try:
            report = diya_knowledge.build(config.notes_dir, config.knowledge_dir, diya_knowledge.known_people(config.db_path))
        except diya_knowledge.KnowledgeError as exc:
            raise HTTPException(status_code=409, detail=printable(str(exc))) from exc
        finally:
            building.release()
        return {
            "report": {
                "notes": report.notes,
                "pages": report.pages,
                "written": len(report.written),
                "unchanged": len(report.unchanged),
                "removed": len(report.removed),
                "left_out": [printable(line, 200) for line in report.skipped[:20]],
                "skipped_names": [printable(name) for name in report.collisions],
                "refused_names": report.refused_names,
                "over_page_limit": report.over_page_limit,
            },
            **listing(),
        }

    def change(body, action):
        try:
            changed = action(config.knowledge_dir, body.name)
        except diya_knowledge.KnowledgeError as exc:
            raise HTTPException(status_code=422, detail=printable(str(exc))) from exc
        return {"changed": changed, **listing()}

    @app.post("/api/knowledge/hide")
    def hide(body: NameBody):
        return change(body, diya_knowledge.hide)

    @app.post("/api/knowledge/unhide")
    def unhide(body: NameBody):
        return change(body, diya_knowledge.unhide)
