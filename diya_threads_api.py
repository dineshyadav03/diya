"""Finding and naming past chats over HTTP: the routes behind the History page's search box and its Rename buttons.

    GET  /api/threads/search?q=...        the chats with a message (or a name) containing q, newest first: {"threads": [{id, created_at, preview, match}]}; a q shorter than two characters finds nothing
    POST /api/threads/{thread_id}/rename  {"title": "..."}  give a chat a name (at most 80 characters; an empty one takes the name back); 404 for a chat that is not there

The list of chats (GET /api/threads) and a chat's history stay in diya_web.py. Like every route these are behind the access token, only GET and POST exist (the API's CORS allows nothing else), and
everything sent back goes through diya_memory.printable() with each line kept short: a chat holds whatever the person or a web page put in it.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_db
from diya_memory import printable

MAX_ID = 2**63 - 1
PREVIEW_CHARS = 300


class RenameBody(BaseModel):
    title: str


def register(app, config, agent):
    """Add the routes to `app`, directly, like every other route. The store is looked up per request."""

    @app.get("/api/threads/search")
    def search(q: str = ""):
        found = agent.store.search_threads(q)
        return {"threads": [{"id": t["id"], "created_at": t["created_at"], "preview": printable(t["preview"], PREVIEW_CHARS), "match": printable(t["match"], PREVIEW_CHARS)} for t in found]}

    @app.post("/api/threads/{thread_id}/rename")
    def rename(thread_id: int, body: RenameBody):
        if not 0 < thread_id <= MAX_ID:
            raise HTTPException(status_code=404, detail=f"there is no chat {printable(thread_id)}")
        if len(body.title) > 4 * diya_db.MAX_THREAD_TITLE:
            raise HTTPException(status_code=422, detail=f"a name is at most {diya_db.MAX_THREAD_TITLE} characters")
        if not agent.store.set_thread_title(thread_id, body.title):
            raise HTTPException(status_code=404, detail=f"there is no chat {thread_id}")
        return {"id": thread_id, "title": printable(" ".join(body.title.split())[:diya_db.MAX_THREAD_TITLE]) or None}
