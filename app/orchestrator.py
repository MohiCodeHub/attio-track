"""The onboarding loop's brain (non-voice parts).

handle_closed_won: triggered by the Attio webhook when a deal -> Won.
  reads context -> (optional) research -> emails a call link -> marks Scheduled.

build_context: pulls the customer picture out of Attio for both the email
  and the voice agent.
"""
from __future__ import annotations

import logging

from app import attio, config, email_client, research

log = logging.getLogger("orchestrator")

CALL_PATH = "/call"
CLOSED_WON_STAGE = "Won 🎉"
# Once onboarding has started/finished we must not re-process (prevents the
# self-trigger loop: our write-backs are themselves record-update events).
ALREADY_HANDLED = {"Scheduled", "Provisioning", "Activated", "Escalated"}


def should_process(record_id: str) -> tuple[bool, str]:
    """Guard so a deal-update webhook only acts on a genuine new 'Won' deal."""
    try:
        vals = attio.simple_values(attio.get_record("deals", record_id))
    except Exception as e:  # noqa: BLE001
        return False, f"could not read deal: {e}"
    stage = vals.get("stage")
    if stage != CLOSED_WON_STAGE:
        return False, f"stage is '{stage}', not '{CLOSED_WON_STAGE}'"
    if vals.get("onboarding_status") in ALREADY_HANDLED:
        return False, f"already handled (onboarding_status={vals.get('onboarding_status')})"
    return True, "ok"


def call_url_for(record_id: str) -> str:
    return f"{config.PUBLIC_BASE_URL}{CALL_PATH}?deal={record_id}"


def build_context(record_id: str) -> dict:
    """Best-effort customer context from a deal record.

    Returns a dict the email + voice agent can both use. Tolerant of missing
    data so the demo never hard-fails.
    """
    ctx = {
        "record_id": record_id,
        "deal_name": "your deal",
        "company": "your company",
        "customer_name": "there",
        "customer_email": config.DEMO_CUSTOMER_EMAIL,
        "plan": "Growth",
        "seats": 10,
        "value": None,
    }
    try:
        deal = attio.get_record("deals", record_id)
        vals = attio.simple_values(deal)
        ctx["deal_name"] = vals.get("name", ctx["deal_name"])
        ctx["value"] = vals.get("value")
        if vals.get("plan"):
            ctx["plan"] = vals["plan"]
        if vals.get("seats"):
            ctx["seats"] = vals["seats"]

        # associated company -> name + domain
        comp_id = _first_ref(deal, "associated_company")
        if comp_id:
            comp = attio.simple_values(attio.get_record("companies", comp_id))
            ctx["company"] = comp.get("name", ctx["company"])
            ctx["domain"] = comp.get("domains") or comp.get("domain")

        # associated person -> name + email
        person_id = _first_ref(deal, "associated_people")
        if person_id:
            person = attio.simple_values(attio.get_record("people", person_id))
            ctx["customer_name"] = person.get("name") or person.get("full_name") or ctx["customer_name"]
            if person.get("email_addresses") or person.get("email_address"):
                ctx["customer_email"] = person.get("email_address") or ctx["customer_email"]
    except Exception as e:  # noqa: BLE001
        log.warning("build_context fell back to defaults: %s", e)
    return ctx


def _first_ref(record: dict, attr: str) -> str | None:
    vals = (record.get("values") or {}).get(attr) or []
    if vals and isinstance(vals[0], dict):
        return vals[0].get("target_record_id")
    return None


def handle_closed_won(record_id: str, enforce_guard: bool = True) -> dict:
    """Inbound webhook flow. Returns a small summary for logging/response.

    enforce_guard=True (default) skips unless the deal is genuinely Won and not
    already handled. Pass False to force-run (manual testing).
    """
    if enforce_guard:
        ok, reason = should_process(record_id)
        if not ok:
            log.info("skip %s: %s", record_id, reason)
            return {"record_id": record_id, "skipped": reason}

    ctx = build_context(record_id)

    # (Layer: research) one-line tailoring via Gemini grounding — best-effort.
    context_line = ""
    try:
        context_line = research.company_briefing_line(ctx.get("company", ""))
    except Exception as e:  # noqa: BLE001
        log.warning("research skipped: %s", e)

    # Email the scheduling link (sandbox: delivers to DEMO_CUSTOMER_EMAIL).
    to = config.DEMO_CUSTOMER_EMAIL
    html = email_client.scheduling_email_html(
        customer_name=ctx["customer_name"],
        company=ctx["company"],
        call_url=call_url_for(record_id),
        context_line=context_line,
    )
    email_resp = {}
    try:
        email_resp = email_client.send_email(
            to=to, subject=f"Welcome to Acme — let's get {ctx['company']} set up", html=html
        )
    except Exception as e:  # noqa: BLE001
        log.error("email send failed: %s", e)

    # Write back to Attio: note + status.
    note = (f"🤖 Onboarding agent triggered (deal Won).\n"
            f"Sent scheduling email to {to}.\n"
            f"{context_line}\n"
            f"Call link: {call_url_for(record_id)}")
    try:
        attio.create_note("deals", record_id, "Onboarding started", note)
    except Exception as e:  # noqa: BLE001
        log.warning("note write failed: %s", e)
    try:
        attio.update_record("deals", record_id, {"onboarding_status": "Scheduled"})
    except Exception as e:  # noqa: BLE001
        log.warning("status write failed: %s", e)

    return {
        "record_id": record_id,
        "company": ctx["company"],
        "emailed": to,
        "email_id": email_resp.get("id"),
        "call_url": call_url_for(record_id),
        "context_line": context_line,
    }
