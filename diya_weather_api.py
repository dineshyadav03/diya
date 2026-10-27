"""The weather over HTTP (docs/HOME_DESIGN.md): the route behind Home's weather panel and the sky.

    GET    /api/weather    {"known": false} until a place is shared; then {"known": true, temp, feels, label, sky, day, sunset} or {"known": true, "problem": words}
    POST   /api/weather    {"lat": ..., "lon": ...}  keep the place the person shared from the browser (rounded to two decimals); 422 for a point that is not on Earth
    DELETE /api/weather    forget the place

Behind the access token like the rest of the API. The place is kept in the computer's own database (diya_weather.py).
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

import diya_config
import diya_weather


class Place(BaseModel):
    lat: float
    lon: float


def register(app, config, agent):
    """Add the routes to `app`, directly, like every other route. Nothing is touched here: the store is looked up when the first request comes."""
    held = {}

    def weather():
        if "it" not in held:
            held["it"] = diya_weather.Weather(agent.store, getattr(config, "tool_allowed_hosts", diya_config.DEFAULT_TOOL_ALLOWED_HOSTS))
        return held["it"]

    @app.get("/api/weather")
    def current():
        return weather().payload()

    @app.post("/api/weather")
    def share(body: Place):
        if not weather().set_location(body.lat, body.lon):
            raise HTTPException(status_code=422, detail="that is not a place on Earth")
        return weather().payload()

    @app.delete("/api/weather")
    def forget():
        weather().forget()
        return {"known": False}
