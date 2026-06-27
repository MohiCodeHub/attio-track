"""The agent's hands on the Acme admin console.

operate_admin(instruction): a freeform browser-use task — the agent passes a
natural-language instruction (built live from the conversation) and a real Chrome
(visible by default) logs into the admin console and carries it out.

fetch_workspace(): read ground-truth workspace state (members, keys, plan, features)
back from Acme so the agent/worker can confirm and email exact details.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from app import config

log = logging.getLogger("provisioning")

ACME_ADMIN_URL = f"{config.PUBLIC_BASE_URL}/acme"
# Visible browser by default — the demo's whole point is watching the agent work.
HEADLESS = os.environ.get("HEADLESS", "0") == "1"

ADMIN_CONTEXT = f"""You are operating the Acme internal admin console to onboard a customer.

How the console works:
- Admin login page: {ACME_ADMIN_URL}/admin/login
  Sign in with email "{config.ACME_ADMIN_USER}" and password "{config.ACME_ADMIN_PASS}".
- On the admin home you can create a workspace (company name, plan, seats).
- After creating it you land on the workspace page, where EVERYTHING else lives:
  invite members (email + role: Viewer/Member/Admin), generate API keys (with a label),
  toggle features (SSO, Audit log, Webhooks), and change the plan.
- To act on an existing workspace, open it from the list on the admin home.

IMPORTANT: This is idempotent. If the workspace already exists, do NOT create a duplicate —
open it instead. If a requested member or API key already exists, leave it as-is. Treat an
already-correct end state as SUCCESS. Make only the changes needed, submit each form once, then stop.

TASK: {{task}}"""


def _slug(company: str) -> str:
    return company.strip().lower().replace(" ", "-")


def fetch_workspace(company: str) -> dict | None:
    try:
        r = httpx.get(f"{ACME_ADMIN_URL}/api/workspaces/{_slug(company)}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("workspace fetch failed: %s", e)
    return None


async def operate_admin(instruction: str) -> str:
    """Run a freeform browser-use task against the admin console. Returns a summary."""
    from browser_use import Agent
    from browser_use.llm import ChatGoogle

    llm = ChatGoogle(model=config.GEMINI_BROWSER_MODEL, api_key=config.GOOGLE_API_KEY)
    task = ADMIN_CONTEXT.format(task=instruction)
    agent = Agent(task=task, llm=llm, headless=HEADLESS)
    result = await agent.run(max_steps=30)
    try:
        return result.final_result() or "done"
    except Exception:  # noqa: BLE001
        return "done"


# --- deterministic fallback (Playwright) for the core create+invite+key path ---
async def provision_workspace_deterministic(company: str, admin_email: str,
                                            plan: str = "Growth", seats: int = 10) -> dict:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        pg = await b.new_page()
        await pg.goto(f"{ACME_ADMIN_URL}/admin/login")
        await pg.fill('input[name="email"]', config.ACME_ADMIN_USER)
        await pg.fill('input[name="password"]', config.ACME_ADMIN_PASS)
        await pg.click('button[type="submit"]')
        await pg.wait_for_url("**/acme/admin")
        await pg.fill('input[name="company"]', company)
        await pg.select_option('select[name="plan"]', plan)
        await pg.fill('input[name="seats"]', str(seats))
        await pg.click('button[type="submit"]')
        await pg.wait_for_url("**/acme/admin/ws/**")
        # invite the customer as Admin
        await pg.fill('input[name="email"]', admin_email)
        await pg.select_option('select[name="role"]', "Admin")
        await pg.click('form[action$="/invite"] button')
        await pg.wait_for_url("**/acme/admin/ws/**")
        # generate an API key
        await pg.click('form[action$="/apikey"] button')
        await pg.wait_for_url("**/acme/admin/ws/**")
        await b.close()
    ws = fetch_workspace(company)
    if not ws:
        raise RuntimeError("provisioning completed but workspace not found")
    return ws


if __name__ == "__main__":
    import sys
    instr = sys.argv[1] if len(sys.argv) > 1 else (
        "Create a workspace for 'Globex Inc' on the Growth plan with 10 seats. "
        "Then invite 'sam@globex.com' as an Admin, generate an API key labelled 'Production', "
        "and enable SSO.")
    print(asyncio.run(operate_admin(instr)))
