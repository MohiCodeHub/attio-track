# Autonomous Onboarding Agent — Build Spec

**Date:** 2026-06-27
**Event:** {Tech: Europe} London AI Hackathon — Attio track (agentic CRM)
**Constraint:** Solo build, one day, submission by 19:00 (public GitHub repo + README + 2-min Loom).

---

## 1. One-line concept

When a deal is marked **Closed Won** in Attio, an autonomous agent onboards the new customer end-to-end: it emails to schedule a session, runs a **live voice onboarding call**, and **does the real admin/provisioning work** in the product's admin panel *during the call* — then writes the outcome back to Attio. No human in the loop until the agent decides it needs one.

The differentiator: this agent doesn't just *message* — it **acts on real systems**. It's an autonomous implementation engineer triggered by CRM state.

---

## 2. The scenario (who the consumer is)

The consumer is a **B2B SaaS company that uses Attio as its CRM**. When they close a deal with another business, their human onboarding/implementation specialist would normally: schedule a kickoff call, provision the customer's workspace, set the plan/entitlements to match what was sold, create the admin user, invite the team, generate API keys, and walk the customer through setup live on a video/voice call.

Our agent replaces that specialist for the long tail of accounts a human never gets to — autonomously.

**"Onboarded" = closeable condition (what the loop closes on):** the customer's workspace is provisioned, admin user + API key issued, and at least one activation milestone confirmed (admin logged in / API key used). This state is written back to Attio as the onboarding record's status → `Activated`.

---

## 3. Domain grounding (why this is real, not a gimmick)

B2B SaaS onboarding is segmented by deal size:
- **Self-serve/SMB:** automated, no human (in-app tours, email, self-serve provisioning).
- **Mid-market → Enterprise ("high-touch"):** a human specialist runs it via **video/voice calls with screen-share**; vendor does provisioning behind the scenes (workspace, entitlements, SSO, API keys, data import); email is the connective tissue (scheduling, requesting pre-work).

Real, automatable admin work after closed-won: **provision tenant/workspace, set plan/entitlements (from the deal), create admin user, invite team, generate API keys, configure settings, verify activation.** Most of this is in-playbook and repetitive — exactly what an agent can own. Custom integration, negotiation, and exec relationship stay human.

---

## 4. Autonomy boundary (escalation as a first-class action)

The agent runs autonomously up to a defined ceiling, defined by three axes:
1. **Authority** — it may provision/invite/issue keys (scoped onboarding actions); it may **not** change billing, alter contract terms, offer discounts, or take destructive admin actions.
2. **Stakes** — it handles the long tail (downside ≈ the touch wouldn't have happened anyway); high-value/at-risk accounts are out of scope.
3. **Ambiguity** — in-playbook setup is autonomous; novel objections or off-script requests trigger escalation.

**Escalation is an action the agent can choose:** when a reply/conversation crosses any axis, it creates an Attio **task** for a human with a one-paragraph briefing and stops. This is a demo highlight — proof the agent reasons about its own limits rather than blindly acting.

---

## 5. Architecture

### Components
1. **Trigger (Attio → us):** Attio fires on `deal.stage = Closed Won` → HTTP POST to our webhook endpoint. Payload is thin (record id); the agent pulls full context itself.
2. **Agent backend (Python / FastAPI):** receives the webhook, orchestrates the loop, exposes the LiveKit token endpoint, hosts the scheduling landing page, and houses the tool functions.
3. **CRM interface (Attio MCP + REST):** the agent reads account/deal context and writes notes, attributes, tasks, and status back. MCP preferred (per brief); REST (`api.attio.com/v2`, Bearer token) as the reliable path.
4. **Email channel:** sends the personalized scheduling email containing the call link. (Inbound reply handling = stretch.)
5. **Voice session (LiveKit Cloud + LiveKit Agents + SLNG):**
   - **LiveKit Cloud** = hosted WebRTC media server that facilitates the call (Room-based).
   - **Browser frontend** = minimal web page (LiveKit JS SDK) the customer opens from the email link; joins the Room.
   - **Agent worker** (LiveKit Agents, Python) = registers with LiveKit Cloud, is dispatched into the Room, runs the `AgentSession` pipeline (VAD → STT → LLM → TTS, with turn detection + barge-in).
   - **SLNG** = the STT/TTS layer, plugged into the AgentSession via the LiveKit SLNG plugin.
6. **Provisioning tool (browser-use):** the agent's LLM calls tool functions (`provision_workspace`, `invite_user`, `generate_api_key`, `set_plan`) that drive a real browser over the **mock "Acme" product** admin panel. This runs *during* the voice call via LiveKit tool-calling.
7. **Mock "Acme" SaaS product (FastAPI + simple HTML admin panel):** the target system the agent operates. We own it → stable for browser-use and the demo.
8. **Pre-call research (Tavily, recommended):** before the call, the agent researches the customer's company to tailor onboarding ("you're a fintech → let's prioritise X"). Genuinely useful context-gathering *and* satisfies the ≥3 partner-tech requirement (see §9).

### Data flow (happy path)
```
Deal → Closed Won (Attio)
  → webhook → agent backend
  → read deal + account context (Attio MCP/REST)
  → [Tavily] research customer company
  → send scheduling email with call link (Email)
  → customer clicks link → browser joins LiveKit Room
  → agent worker dispatched → voice conversation (SLNG STT/TTS, Claude LLM)
  → agent calls tools → browser-use provisions in Acme admin panel (live)
  → agent reads back credentials, confirms activation
  → write notes + status (Activated) + outcome to Attio
  → [if off-script] create Attio task for human + stop (escalation)
```

---

## 6. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ (LiveKit Agents + browser-use are Python) |
| Agent backend / API | FastAPI |
| Voice transport | LiveKit Cloud (WebRTC), LiveKit Agents framework |
| Speech (STT/TTS) | SLNG via LiveKit SLNG plugin |
| LLM (reasoning + voice) | Anthropic Claude — `claude-sonnet-4-6` for the realtime voice loop + browser-use (latency); `claude-opus-4-8` for the planning/decision step |
| Browser automation | `browser-use` (Playwright + Claude) on the Acme admin panel |
| CRM | Attio (MCP + REST API) |
| Email | Resend (send); inbound webhook = stretch |
| Pre-call research | Tavily (recommended) |
| Mock product | FastAPI + minimal HTML admin panel |
| Frontend (call UI) | Static HTML + LiveKit JS SDK |
| Public URLs (demo) | ngrok / cloudflared tunnel (for Attio webhook + email link landing) |
| Security (side challenge) | Aikido repo scan + screenshot |

---

## 7. Layered build plan (each layer is a standalone working demo)

**Layer 0 — Mock Acme product + admin panel.** Login, create workspace, invite user, generate API key, set plan. Seeded admin creds. *(Prereq for provisioning.)*

**Layer 1 — Email + Attio loop (committed core).** Closed-Won trigger → read context → send scheduling email with link → write a note + status to Attio. *Always works; proves the CRM-driven loop.*

**Layer 2 — Browser-use provisioning (committed core).** Agent provisions a workspace + API key in the Acme admin panel (triggered async first, before wiring to voice). *Proves "agent acts on real systems."*

**Layer 3 — Live voice onboarding (hero).** LiveKit + SLNG: customer clicks link → browser voice room → agent guides them through onboarding by voice.

**Layer 4 — Provisioning *during* the call (the wow).** Voice agent calls the Layer-2 tools mid-conversation and reads back the result.

**Layer 5 — Stretch.** Inbound email reply handling (multi-turn scheduling); escalation task demo; renewal trigger as a second loop; screen-vision.

Stop-loss: if a layer isn't solid, the previous layer is the demo. Record the Loom against the highest solid layer.

---

## 8. API keys / configs required

You'll need to create accounts and set these as environment variables (`.env`). **Action items for you are marked 🔑.**

### Attio
- 🔑 `ATTIO_API_KEY` — workspace API token (Settings → Developers → API keys). Used for REST + MCP.
- 🔑 Configure the **trigger**: an Attio automation/workflow (or API webhook) that, when a deal's stage → Closed Won, sends an HTTP POST to `https://<your-tunnel>/webhooks/attio`. *(To verify during build: whether Attio's no-code Workflows expose an outbound HTTP action; if not, use REST API webhook subscriptions, or a polling fallback that lists deals filtered by stage. A polling fallback is the bulletproof demo path.)*
- 🔑 A test Attio workspace with the **Deals** object and a sample deal we can flip to Closed Won on camera.

### LiveKit
- 🔑 `LIVEKIT_URL` (e.g. `wss://<project>.livekit.cloud`)
- 🔑 `LIVEKIT_API_KEY`
- 🔑 `LIVEKIT_API_SECRET`
  (from a free LiveKit Cloud project)

### SLNG
- 🔑 `SLNG_API_KEY` — from slng.ai (hackathon partner credentials). Used by the LiveKit SLNG plugin for STT/TTS.

### Anthropic
- 🔑 `ANTHROPIC_API_KEY` — LLM for the voice agent reasoning + browser-use.

### Email (Resend)
- 🔑 `RESEND_API_KEY`
- 🔑 A verified sending domain (or use Resend's onboarding/sandbox sender for the demo).

### Tavily (recommended, 3rd partner tech)
- 🔑 `TAVILY_API_KEY` — pre-call company research.

### Tunnel (demo)
- 🔑 ngrok or cloudflared installed + authed (public URL for the Attio webhook and the email's call link).

### Mock Acme product
- No external keys. Seed an admin login (`ACME_ADMIN_USER` / `ACME_ADMIN_PASS`) for browser-use.

### Aikido (side challenge, build-agnostic)
- 🔑 Aikido account; connect the public GitHub repo; screenshot the report before submission.

---

## 9. Partner-tech requirement (≥3)

- **Attio** — trigger source + write-back target (core).
- **SLNG** — voice STT/TTS in the live onboarding call.
- **Tavily** — pre-call customer research (recommended; restores the 3rd partner cleanly and adds real value).
- **Aikido** — security scan (separate €1000 side challenge; do regardless).

LiveKit is the voice transport but is not assumed to be a counted partner. With Attio + SLNG + Tavily we satisfy ≥3 comfortably. **Open decision:** confirm Tavily is in (recommended) vs relying on Aikido as the 3rd.

---

## 10. Demo script (2-min Loom, against highest solid layer)

1. Show Attio: a deal in late stage. Flip it to **Closed Won**. (0:15)
2. Cut to: the agent's scheduling email arriving; click the call link. (0:20)
3. Browser voice room — greet the agent; it knows the customer (context from Attio + Tavily). (0:30)
4. Agent guides onboarding by voice; mid-call says "setting up your workspace now" → **show browser-use provisioning in the Acme admin panel live** → reads back the API key. (0:45)
5. Cut to Attio: notes appended, status → **Activated**, outcome logged — no human touched it. (0:10)
6. (If built) show the escalation case: a curveball reply → agent creates a human task with a briefing. (0:15)

---

## 11. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Live voice (LiveKit+SLNG) broken at 19:00 | Layered build; Layers 1–2 demo without voice. Record against highest solid layer. |
| browser-use flaky on camera | We own the Acme panel (stable); have an MCP/API path on Acme as fallback; pre-run to warm. |
| Attio trigger not firing reliably | Polling fallback (list deals by stage) guarantees the loop fires for the demo. |
| Inbound email infra | Cut multi-turn email; scheduling via a link in one outbound email. |
| Too many moving parts | Strict layer order; do not start Layer N+1 until N is solid. |
| Admin-access safety optics | Scoped onboarding-only actions; escalation for anything off-script. |

---

## 12. Out of scope (YAGNI)

- Inbound lead enrichment/routing (Attio does this natively; dropped earlier).
- Google Meet / video / screen-vision (needs Recall.ai; replaced by browser web voice).
- Real third-party product integration (mock Acme instead).
- Multi-turn email negotiation (link-based scheduling instead).
- Renewal/churn loop (separate stretch; same pattern, different trigger).

---

## 13. Open decisions to confirm before planning

1. **Tavily in or out** as the 3rd partner tech (recommended: in, for pre-call research).
2. **Trigger mechanism:** native Attio workflow HTTP action vs REST webhook vs polling fallback — resolve early during build (polling is the safe default).
3. **Committed scope vs hero:** confirm Layers 1–2 are the committed deliverable and Layers 3–4 are the hero target.
