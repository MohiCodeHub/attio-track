"""Attio REST client — read deal/company/person context, write notes, status, tasks.

Kept deliberately small: just the operations the onboarding loop needs.
Docs: https://docs.attio.com/rest-api
"""
import httpx

from app import config

_HEADERS = {
    "Authorization": f"Bearer {config.ATTIO_API_KEY}",
    "Content-Type": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(base_url=config.ATTIO_BASE, headers=_HEADERS, timeout=30)


def get_record(object_slug: str, record_id: str) -> dict:
    """Fetch a single record (e.g. object_slug='deals')."""
    with _client() as c:
        r = c.get(f"/objects/{object_slug}/records/{record_id}")
        r.raise_for_status()
        return r.json().get("data", {})


def list_records(object_slug: str, limit: int = 50) -> list[dict]:
    with _client() as c:
        r = c.post(f"/objects/{object_slug}/records/query", json={"limit": limit})
        r.raise_for_status()
        return r.json().get("data", [])


def simple_values(record: dict) -> dict:
    """Flatten Attio's verbose attribute envelopes into plain {attr: value}.

    Attio returns each attribute as a list of value-objects; we take the first
    and pull whatever scalar field it carries (value / status / target_record_id...).
    """
    out: dict = {}
    for attr, vals in (record.get("values") or {}).items():
        if not vals:
            continue
        v = vals[0]
        for key in ("value", "status", "option", "currency_value", "target_record_id",
                    "email_address", "full_name", "referenced_actor_id"):
            if key in v and v[key] is not None:
                out[attr] = v[key].get("title") if isinstance(v[key], dict) else v[key]
                break
    return out


def create_note(parent_object: str, parent_record_id: str, title: str, content: str) -> dict:
    """Append a note to a record (shows in the record's timeline)."""
    payload = {
        "data": {
            "parent_object": parent_object,
            "parent_record_id": parent_record_id,
            "title": title[:100],
            "format": "plaintext",
            "content": content,
        }
    }
    with _client() as c:
        r = c.post("/notes", json=payload)
        r.raise_for_status()
        return r.json().get("data", {})


def update_record(object_slug: str, record_id: str, values: dict) -> dict:
    """Patch attribute values on a record (e.g. {'onboarding_status': 'Activated'})."""
    payload = {"data": {"values": values}}
    with _client() as c:
        r = c.patch(f"/objects/{object_slug}/records/{record_id}", json=payload)
        r.raise_for_status()
        return r.json().get("data", {})


def create_task(content: str, linked_object: str | None = None,
                linked_record_id: str | None = None, deadline_iso: str | None = None) -> dict:
    """Create a task (used by the agent to escalate to a human)."""
    data: dict = {"content": content, "format": "plaintext", "is_completed": False}
    if linked_object and linked_record_id:
        data["linked_records"] = [{"target_object": linked_object,
                                   "target_record_id": linked_record_id}]
    if deadline_iso:
        data["deadline_at"] = deadline_iso
    with _client() as c:
        r = c.post("/tasks", json={"data": data})
        r.raise_for_status()
        return r.json().get("data", {})


def whoami() -> dict:
    """Validate the token / connection."""
    with _client() as c:
        r = c.get("/self")
        r.raise_for_status()
        return r.json()
