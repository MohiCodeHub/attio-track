"""LiveKit voice agent worker — the live onboarding call.

Pipeline: Silero VAD -> SLNG STT -> Gemini LLM -> SLNG TTS.

The agent is freeform and active: it operates the Acme admin console with a real
browser (browser-use, visible) based on the live conversation, emails the customer,
and writes outcomes back to Attio.

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


SYSTEM_PROMPT = """You are Acme's autonomous onboarding specialist on a LIVE VOICE call with a \
brand-new customer right after they signed. Be warm, brief, natural, and proactive. You don't just
talk — you actively DO the setup in Acme's admin console using your browser while you speak.

YOUR TOOLS
- operate_admin(instruction, spoken_preface): drive the Acme admin console with a natural-language
  instruction. You can: create a workspace (company, plan, seats), invite members with a role
  (Viewer/Member/Admin), generate API keys, toggle features (SSO, Audit log, Webhooks), and change
  the plan. Always use the customer's real COMPANY NAME. ALWAYS pass spoken_preface — a short, natural
  sentence saying what you're about to do (e.g. "Sure, I'm adding jane@globex.com to your members list
  now, one moment") — it is spoken BEFORE the browser work, which takes ~a minute, so the customer is
  never left in silence. Returns the resulting workspace state.
- complete_onboarding(): emails the customer their sign-in details (email + temporary password) and
  their API key, and marks them Activated in the CRM. Call this ONCE after the workspace exists, the
  customer has been invited as an Admin, and an API key has been generated.
- send_customer_email(subject, body): send the customer a freeform email (e.g. a recap, or extra
  info they ask for during the call).
- escalate_to_human(reason): hand off when something needs authority (discounts, contract/billing
  changes) or the customer is hostile / the request is off-script.

FLOW
1. Greet them by name and congratulate them.
2. Confirm the basics out loud (company, plan, seats).
3. Say you're setting things up now, then call operate_admin to: create their workspace, invite them
   (their email) as an Admin, and generate an API key — in a single instruction. If they mention
   needs (SSO, more seats, inviting a colleague), fold those into the instruction.
4. Briefly tell them what you did, then call complete_onboarding to email their credentials. Tell them
   to check their inbox. If asked what they sign in with: their email + the temporary password in that
   welcome email. IMPORTANT: call operate_admin ONCE for the initial setup. After it returns the
   workspace state, do NOT call it again for the same setup — move on. Only call operate_admin again
   for genuinely NEW changes the customer asks for later.
5. Keep listening and ACT on what they say — invite teammates, enable features, change plan
   (operate_admin), or send them info (send_customer_email). ALWAYS give a spoken_preface first so
   they hear what you're doing before the ~minute-long browser step (never call operate_admin silently).

Only state what actually happened — rely on the tool results, never invent keys, passwords, or actions.
Keep spoken replies short."""


def _summarize_ws(ws: dict | None) -> str:
    if not ws:
        return "No workspace found yet — you may need to create it first."
    members = ", ".join(f"{m['email']} ({m['role']})" for m in ws.get("members", [])) or "none"
    feats = ", ".join(f for f, v in ws.get("features", {}).items() if v) or "none"
    return (f"Workspace '{ws['company']}' — {ws['plan']} plan, {ws['seats']} seats. "
            f"Members: {members}. API keys: {len(ws.get('api_keys', []))}. Features on: {feats}.")


class OnboardingAgent(Agent):
    def __init__(self, deal_id: str, ctx: dict):
        self.deal_id = deal_id
        self.ctx = ctx
        self._busy = False
        extra = (f"\n\nWHAT YOU KNOW ABOUT THIS CUSTOMER:\n"
                 f"- Name: {ctx.get('customer_name')}\n"
                 f"- Company: {ctx.get('company')}\n"
                 f"- Plan: {ctx.get('plan')}  |  Seats: {ctx.get('seats')}\n"
                 f"- Their email (use this for the Admin invite + welcome email): {ctx.get('customer_email')}\n")
        if ctx.get("context_line"):
            extra += f"- Note: {ctx['context_line']}\n"
        super().__init__(instructions=SYSTEM_PROMPT + extra)

    @function_tool
    async def operate_admin(self, context: RunContext, instruction: str, spoken_preface: str) -> str:
        """Drive the Acme admin console to carry out a setup instruction (create workspace, invite
        members, generate API keys, toggle features, change plan). Use the customer's real company name.

        spoken_preface: a short, natural sentence telling the customer what you're about to do, e.g.
        "Sure, I'm adding jane@globex.com to your members list now — give me a few seconds." This is
        spoken aloud BEFORE the browser work begins (which takes a little while), so they're never
        left in silence."""
        log.info("operate_admin: %s", instruction)
        instr_l = instruction.lower()
        # 1) Busy lock: while a browser task is running (~60s), refuse duplicates so the
        # model doesn't re-issue the same action on every new turn.
        if getattr(self, "_busy", False):
            return "I'm still finishing the previous step — one moment, I'll confirm when it's done."
        # 2) Idempotency: skip the browser if the requested end-state already holds.
        existing = provisioning.fetch_workspace(self.ctx.get("company", ""))
        if existing:
            if "creat" in instr_l and existing.get("members") and existing.get("api_keys"):
                return "The workspace is already set up. " + _summarize_ws(existing)
            featmap = {"sso": "SSO", "webhook": "Webhooks", "audit": "Audit log"}
            wants_enable = any(w in instr_l for w in ("enable", "turn on", " on", "activate"))
            for kw, fname in featmap.items():
                if kw in instr_l and wants_enable and existing.get("features", {}).get(fname):
                    return f"{fname} is already enabled for them. " + _summarize_ws(existing)
        # announce, then do the work
        try:
            await context.session.say(spoken_preface).wait_for_playout()
        except Exception as e:  # noqa: BLE001
            log.warning("preface say failed: %s", e)
        self._busy = True
        try:
            await provisioning.operate_admin(instruction)
        except Exception as e:  # noqa: BLE001
            log.error("operate_admin failed: %s", e)
            return f"The browser task ran into a problem ({e}). You can retry or escalate to a human."
        finally:
            self._busy = False
        try:
            attio.update_record("deals", self.deal_id, {"onboarding_status": "Provisioning"})
        except Exception:  # noqa: BLE001
            pass
        return "Done. " + _summarize_ws(provisioning.fetch_workspace(self.ctx.get("company", "")))

    @function_tool
    async def complete_onboarding(self, context: RunContext) -> str:
        """Email the customer their sign-in details + API key and mark them Activated in the CRM.
        Call once the workspace exists, the customer is invited as Admin, and an API key is generated."""
        c = self.ctx
        ws = provisioning.fetch_workspace(c.get("company", ""))
        if not ws or not ws.get("members"):
            return "No workspace or members found yet — create the workspace and invite the customer first."
        email = (c.get("customer_email") or "").lower()
        member = next((m for m in ws["members"] if m["email"].lower() == email), ws["members"][0])
        api_key = ws["api_keys"][-1]["key"] if ws.get("api_keys") else "(no API key generated yet)"
        dashboard = f"{config.PUBLIC_BASE_URL}/acme/login"
        emailed = False
        try:
            email_client.send_email(
                to=member["email"], subject=f"Your {ws['company']} workspace is ready 🎉",
                html=email_client.welcome_email_html(
                    c.get("customer_name", "there"), ws["company"], ws["plan"], ws["seats"],
                    api_key, dashboard, member["email"], member["password"]))
            emailed = True
        except Exception as e:  # noqa: BLE001
            log.warning("welcome email failed: %s", e)
        note = (f"🤖 Onboarding complete — provisioned autonomously on the call.\n"
                f"{_summarize_ws(ws)}\nWelcome email sent: {emailed} -> {member['email']}")
        try:
            attio.create_note("deals", self.deal_id, "Onboarding complete", note)
            attio.update_record("deals", self.deal_id, {"onboarding_status": "Activated"})
        except Exception as e:  # noqa: BLE001
            log.warning("attio write-back failed: %s", e)
        return (f"Welcome email sent to {member['email']} with their login and API key, and the CRM is "
                f"updated to Activated. Tell them warmly they're all set and to check their inbox."
                if emailed else "Could not send the email; tell them their details are in the dashboard.")

    @function_tool
    async def send_customer_email(self, context: RunContext, subject: str, body: str) -> str:
        """Send the customer a freeform email (e.g. a recap or extra info they asked for)."""
        to = self.ctx.get("customer_email") or config.DEMO_CUSTOMER_EMAIL
        html = f"<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif'>{body.replace(chr(10), '<br>')}</div>"
        try:
            email_client.send_email(to=to, subject=subject, html=html)
            return f"Email '{subject}' sent to {to}."
        except Exception as e:  # noqa: BLE001
            return f"Could not send the email: {e}"

    @function_tool
    async def escalate_to_human(self, context: RunContext, reason: str) -> str:
        """Hand off to a human specialist (authority needed, hostile, or off-script)."""
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
        # Harden against echo-triggered self-interruption (speaker feedback):
        # require a real, multi-word utterance before cutting the agent off.
        min_interruption_duration=0.8,
        min_interruption_words=3,
        resume_false_interruption=True,
    )


async def entrypoint(ctx: JobContext):
    await ctx.connect()
    name = ctx.room.name
    deal_id = name.split("--", 1)[1] if "--" in name else name.replace("onboard-", "")
    log.info("call started for deal %s (room %s)", deal_id, name)

    data = orchestrator.build_context(deal_id)
    try:
        from app import research
        data["context_line"] = research.company_briefing_line(data.get("company", ""))
    except Exception:  # noqa: BLE001
        data["context_line"] = ""

    session = _build_session()
    await session.start(agent=OnboardingAgent(deal_id, data), room=ctx.room)
    await session.generate_reply(
        instructions=f"Greet {data.get('customer_name')} from {data.get('company')} warmly and start onboarding.")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
