# Autonomous Onboarding Agent — Agentic CRM on Attio

When a deal is marked **Won** in Attio, an autonomous agent onboards the new customer
end-to-end: it emails a call link, runs a **live voice onboarding call**, and **provisions
the customer's workspace in the product's admin panel during the call** — then writes the
outcome back to Attio. No human in the loop until the agent decides it needs one.

The differentiator: this agent doesn't just *message* — it **acts on real systems**.

> Built for the {Tech: Europe} London AI Hackathon — Attio track.
> Partner tech: **Attio** (trigger + system of record), **SLNG** (voice STT/TTS),
> **Google Gemini** (reasoning + browser control). Security scanned with **Aikido**.

---

## How it works

```
Deal → "Won 🎉" (Attio)
  → Attio workflow HTTP action → POST /webhooks/attio  (this service, on Render)
  → read deal + company + person context (Attio REST)
  → Gemini Google-Search grounding: one-line tailoring
  → Resend: email the customer a call link
  → mark deal onboarding_status = Scheduled
  → customer clicks link → browser joins a LiveKit room
  → voice worker dispatched (Silero VAD → SLNG STT → Gemini → SLNG TTS)
  → agent confirms details, then calls provision_workspace tool:
        browser-use / Playwright drives the Acme admin panel →
        creates workspace, sets plan/seats, invites admin, generates API key
  → agent reads back "you're all set", writes note + onboarding_status = Activated
  → (off-script / needs authority) → escalate_to_human → Attio task + Escalated
```

## Architecture

| Piece | File | Role |
|---|---|---|
| Web service | `app/main.py` | Attio webhook, LiveKit token, call UI, mounts Acme |
| Orchestrator | `app/orchestrator.py` | context → research → email → write-back |
| Attio client | `app/attio.py` | read records, write notes/status/tasks |
| Email | `app/email_client.py` | Resend send |
| Research | `app/research.py` | Gemini + Google Search grounding |
| Mock product | `app/acme.py` | "Acme" SaaS + admin panel (provisioning target) |
| Provisioning | `app/provisioning.py` | browser-use (agentic) + Playwright (fallback) |
| Voice worker | `agent/worker.py` | LiveKit AgentSession + tools (the live call) |

The **web service** deploys to Render (public webhook URL). The **voice worker** and
**browser automation** run locally during the demo — they connect outbound to LiveKit
Cloud and to the web service's `/acme` panel, so they need no hosting.

## Setup

1. Python 3.12, then:
   ```bash
   python3.12 -m venv .venv && . .venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Copy `.env.example` → `.env` and fill in keys (Attio, Google Gemini, SLNG, LiveKit, Resend).
3. **Enable the Deals object** in Attio (Settings → Objects → Deals), then seed the demo:
   ```bash
   python -m scripts.seed_attio
   ```

## Run locally

```bash
# 1. web service (webhook + token + call UI + Acme)
uvicorn app.main:app --port 8000

# 2. expose it publicly for Attio's webhook + the email call link
cloudflared tunnel --url http://localhost:8000   # or: ngrok http 8000
#   set PUBLIC_BASE_URL in .env to the tunnel URL, restart uvicorn

# 3. voice worker
python -m agent.worker dev
```

Trigger the loop without the workflow:
```bash
curl -X POST $PUBLIC_BASE_URL/webhooks/attio -H 'content-type: application/json' \
  -d '{"record_id":"<deal_record_id>"}'
```

## Wiring the Attio trigger (no-code)

In Attio → **Workflows** → New workflow:
- **Trigger:** Record updated → object *Deals* → when **Stage** becomes **Won 🎉**
- **Action:** HTTP request → `POST {PUBLIC_BASE_URL}/webhooks/attio`,
  JSON body `{"record_id": "{{ record.id.record_id }}"}`

## Deploy the web service to Render

`render.yaml` is a Blueprint. After the first deploy, set `PUBLIC_BASE_URL` to the
service's own URL and redeploy so the call links and Acme panel resolve correctly.
(The web service uses `requirements-web.txt` — it does not need LiveKit/Playwright.)

## Demo (2-min Loom)

1. Attio: move the demo deal to **Won 🎉**.
2. Scheduling email arrives → click the call link.
3. Browser voice call: the agent greets you by name, confirms plan/seats.
4. It says "setting up your workspace" → the Acme admin panel fills in live → API key generated.
5. Back in Attio: note added, `onboarding_status = Activated`. No human touched it.
6. (Optional) a hostile/discount reply → agent escalates → Attio task created.

## Provisioning modes

`PROVISION_MODE=browser_use` (default) drives the admin panel with a Gemini-controlled
browser (the agentic "wow"); it auto-falls back to deterministic Playwright on any error.
Set `PROVISION_MODE=playwright` to force the deterministic path for a guaranteed demo take.
