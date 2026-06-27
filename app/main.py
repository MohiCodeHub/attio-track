"""FastAPI web service: Attio webhook + LiveKit token + call UI + mock Acme.

This is the public service deployed to Render. The LiveKit agent worker
(agent/worker.py) runs separately and connects outbound to LiveKit Cloud.
"""
import logging
import secrets
import time
from pathlib import Path

import jwt
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import acme, config, orchestrator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("web")

app = FastAPI(title="Autonomous Onboarding Agent")
app.include_router(acme.router)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def room_for(deal_id: str) -> str:
    # Unique per call so every join creates a fresh room and the agent is always
    # dispatched (LiveKit auto-dispatch fires on room creation, not on re-join).
    # Worker parses the deal id from the part after "--".
    return f"onboard-{secrets.token_hex(3)}--{deal_id}"


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/webhooks/attio")
async def attio_webhook(request: Request):
    """Triggered by an Attio workflow when a deal stage -> Won.

    Accepts a flexible payload; we just need the deal record_id. Configure the
    Attio workflow's HTTP action body as: {"record_id": "{{record.id}}"}.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    record_id = _extract_record_id(payload)
    force = str(request.query_params.get("force", "")).lower() in ("1", "true", "yes")
    log.info("attio webhook: record_id=%s force=%s payload_keys=%s", record_id, force, list(payload)[:8])
    if not record_id:
        return JSONResponse({"error": "no record_id in payload", "got": payload}, status_code=400)
    result = orchestrator.handle_closed_won(record_id, enforce_guard=not force)
    return {"status": "ok", "result": result}


def _extract_record_id(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    # direct
    for k in ("record_id", "recordId", "id"):
        v = payload.get(k)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and v.get("record_id"):
            return v["record_id"]
    # Attio webhook delivery shape: {"events":[{"id":{"record_id": "..."}}]}
    events = payload.get("events")
    if isinstance(events, list) and events:
        ev = events[0]
        if isinstance(ev, dict):
            rid = (ev.get("id") or {}).get("record_id") if isinstance(ev.get("id"), dict) else None
            return rid or ev.get("record_id")
    # other nested shapes
    for path in (("data", "id", "record_id"), ("event", "record_id")):
        node = payload
        ok = True
        for p in path:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                ok = False
                break
        if ok and isinstance(node, str):
            return node
    return None


@app.get("/api/token")
def mint_token(deal: str, identity: str = "customer"):
    """Mint a LiveKit access token so the customer's browser can join the room."""
    room = room_for(deal)
    now = int(time.time())
    claims = {
        "iss": config.LIVEKIT_API_KEY,
        "sub": identity,
        "name": "Customer",
        "nbf": now - 5,
        "exp": now + 60 * 60,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
        },
        "metadata": deal,  # deal record id, available to the agent
    }
    token = jwt.encode(claims, config.LIVEKIT_API_SECRET, algorithm="HS256")
    return {"token": token, "url": config.LIVEKIT_URL, "room": room}


@app.get("/call", response_class=HTMLResponse)
def call_page(deal: str = ""):
    html = (STATIC_DIR / "call.html").read_text()
    return HTMLResponse(html.replace("__DEAL__", deal))


@app.get("/")
def root():
    return {
        "service": "autonomous-onboarding-agent",
        "try": ["/acme/login", "/call?deal=<deal_id>", "POST /webhooks/attio"],
    }
