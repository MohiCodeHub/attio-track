"""LiveKit voice agent worker — the live onboarding call (Layers 3 & 4).

Pipeline: Silero VAD -> SLNG STT -> Gemini LLM -> SLNG TTS.
Tools the agent can call mid-conversation:
  - provision_workspace: drives the Acme admin panel (browser-use / Playwright),
    then writes the result back to Attio (note + status=Activated).  ← the "wow"
  - escalate_to_human: creates an Attio task and stops (the autonomy boundary).

Run locally:  python -m agent.worker dev
"""
from __future__ import annotations

import logging

from livekit.agents import (
    Agent, AgentSession, JobContext, WorkerOptions, cli, function_tool, RunContext,
)
from livekit.plugins import silero, google, slng

from app import attio, config, email_client, orchestrator, provisioning

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")


SYSTEM_PROMPT = """You are Acme's autonomous onboarding assistant, on a LIVE VOICE call with a \
brand-new customer right after they signed. Be warm, brief, and natural — short spoken sentences.

Your job on this call:
1. Greet them by name and congratulate them on getting started with Acme.
2. Briefly confirm the setup details you already have (their company, plan, and seat count).
3. Once confirmed, CALL the provision_workspace tool to create their workspace live. While it runs,
   tell them you're setting things up right now.
4. After it succeeds, tell them their workspace is live and that you've JUST EMAILED them a welcome
   email containing their API key and a link to their dashboard. Tell them to check their inbox.
   Do NOT read the long API key aloud. Do NOT invent any other emails, passwords, or "secure
   password-setup links" — the only thing sent is that one welcome email with the API key + dashboard
   link. Only state what actually happened.
5. Offer one or two helpful next steps, then wrap up warmly.

Boundaries — if the customer becomes hostile, asks for a discount, a contract or billing change, or
anything outside standard setup that needs authority, do NOT improvise. CALL escalate_to_human with a
short reason, tell them a specialist will follow up shortly, and stop trying to resolve it yourself.

Keep every reply short enough to be spoken naturally."""


class OnboardingAgent(Agent):
    def __init__(self, deal_id: str, ctx: dict):
        self.deal_id = deal_id
        self.ctx = ctx
        extra = (f"\n\nWhat you know about this customer:\n"
                 f"- Name: {ctx.get('customer_name')}\n"
                 f"- Company: {ctx.get('company')}\n"
                 f"- Plan: {ctx.get('plan')}  |  Seats: {ctx.get('seats')}\n"
                 f"- Admin email to invite: {ctx.get('customer_email')}\n")
        if ctx.get("context_line"):
            extra += f"- Note: {ctx['context_line']}\n"
        super().__init__(instructions=SYSTEM_PROMPT + extra)

    @function_tool
    async def provision_workspace(self, context: RunContext) -> str:
        """Create the customer's Acme workspace (workspace, plan, seats, admin invite, API key)
        and record the outcome in the CRM. Call this once the setup details are confirmed."""
        c = self.ctx
        log.info("provisioning workspace for %s", c.get("company"))
        try:
            ws = await provisioning.provision_workspace(
                company=c.get("company") or "New Customer",
                admin_email=c.get("customer_email"),
                plan=c.get("plan", "Growth"),
                seats=int(c.get("seats", 10) or 10),
            )
        except Exception as e:  # noqa: BLE001
            log.error("provisioning failed: %s", e)
            return "Provisioning failed unexpectedly. Tell the customer you'll have a specialist finish setup."

        # Send the welcome email with the real API key + dashboard link.
        dashboard_url = f"{config.PUBLIC_BASE_URL}/acme/login"
        emailed = False
        try:
            email_client.send_email(
                to=c.get("customer_email") or config.DEMO_CUSTOMER_EMAIL,
                subject=f"Your {ws['company']} workspace is ready 🎉",
                html=email_client.welcome_email_html(
                    customer_name=c.get("customer_name", "there"),
                    company=ws["company"], plan=ws["plan"], seats=ws["seats"],
                    api_key=ws["api_key"], dashboard_url=dashboard_url,
                    admin_email=ws["admin_email"]),
            )
            emailed = True
        except Exception as e:  # noqa: BLE001
            log.warning("welcome email failed: %s", e)

        # Write back to Attio (best-effort).
        note = (f"🤖 Onboarding call complete — workspace provisioned autonomously.\n"
                f"Company: {ws['company']} | Plan: {ws['plan']} | Seats: {ws['seats']}\n"
                f"Admin invited: {ws['admin_email']} | API key: {ws['api_key']}\n"
                f"Welcome email sent: {emailed}")
        try:
            attio.create_note("deals", self.deal_id, "Onboarding complete", note)
            attio.update_record("deals", self.deal_id, {"onboarding_status": "Activated"})
        except Exception as e:  # noqa: BLE001
            log.warning("attio write-back failed: %s", e)

        sent = ("A welcome email with the API key and dashboard link was emailed to "
                f"{c.get('customer_email')}." if emailed else
                "The welcome email could not be sent; tell them the API key is in their dashboard.")
        return (f"Success. Workspace '{ws['company']}' is live on the {ws['plan']} plan with "
                f"{ws['seats']} seats. {sent} Tell the customer warmly that they're all set and to "
                f"check their inbox.")

    @function_tool
    async def escalate_to_human(self, context: RunContext, reason: str) -> str:
        """Hand off to a human specialist. Call when the request needs authority (discounts,
        contract/billing changes) or the customer is hostile / the situation is off-script."""
        log.info("escalating: %s", reason)
        briefing = (f"🤖 Onboarding agent escalation for deal {self.deal_id}.\n"
                    f"Customer: {self.ctx.get('customer_name')} ({self.ctx.get('company')}).\n"
                    f"Reason: {reason}\nA human specialist should follow up.")
        try:
            attio.create_task(briefing, linked_object="deals", linked_record_id=self.deal_id)
            attio.update_record("deals", self.deal_id, {"onboarding_status": "Escalated"})
        except Exception as e:  # noqa: BLE001
            log.warning("escalation write failed: %s", e)
        return "Logged for a human specialist. Tell the customer someone will follow up shortly."


def _build_session() -> AgentSession:
    return AgentSession(
        vad=silero.VAD.load(),
        stt=slng.STT(api_key=config.SLNG_API_KEY, model=config.SLNG_STT_MODEL),
        llm=google.LLM(model=config.GEMINI_VOICE_MODEL, api_key=config.GOOGLE_API_KEY),
        tts=slng.TTS(api_key=config.SLNG_API_KEY, model=config.SLNG_TTS_MODEL),
    )


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    name = ctx.room.name
    deal_id = name.split("--", 1)[1] if "--" in name else name.replace("onboard-", "")
    log.info("call started for deal %s (room %s)", deal_id, ctx.room.name)

    data = orchestrator.build_context(deal_id)
    try:
        data["context_line"] = __import__("app.research", fromlist=["company_briefing_line"]) \
            .company_briefing_line(data.get("company", ""))
    except Exception:
        data["context_line"] = ""

    session = _build_session()
    await session.start(agent=OnboardingAgent(deal_id, data), room=ctx.room)
    await session.generate_reply(
        instructions=f"Greet {data.get('customer_name')} from {data.get('company')} warmly and start onboarding."
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
