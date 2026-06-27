"""Provisioning tool — the agent's "hands" on the Acme admin panel.

Two implementations of the same action:
  - provision_via_playwright: deterministic, rock-solid (demo-safe default).
  - provision_via_browser_use: agentic — an LLM drives the browser (the "wow").

provision_workspace() picks by PROVISION_MODE and falls back to Playwright if
the agentic path errors, so the loop always completes.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from app import config

log = logging.getLogger("provisioning")

ACME_ADMIN_URL = f"{config.PUBLIC_BASE_URL}/acme"
PROVISION_MODE = os.environ.get("PROVISION_MODE", "browser_use")  # or "playwright"


def _slug(company: str) -> str:
    return company.strip().lower().replace(" ", "-")


def _fetch_workspace(company: str) -> dict | None:
    try:
        r = httpx.get(f"{ACME_ADMIN_URL}/api/workspaces/{_slug(company)}", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("workspace fetch failed: %s", e)
    return None


async def provision_via_playwright(company: str, admin_email: str, plan: str, seats: int) -> dict:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=os.environ.get("HEADLESS", "1") == "1")
        page = await browser.new_page()
        await page.goto(f"{ACME_ADMIN_URL}/admin/login")
        await page.fill('input[name="email"]', config.ACME_ADMIN_USER)
        await page.fill('input[name="password"]', config.ACME_ADMIN_PASS)
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/acme/admin")
        await page.fill('input[name="company"]', company)
        await page.fill('input[name="admin_email"]', admin_email)
        await page.select_option('select[name="plan"]', plan)
        await page.fill('input[name="seats"]', str(seats))
        await page.click('button[type="submit"]')
        await page.wait_for_url("**/acme/admin")
        await browser.close()
    ws = _fetch_workspace(company)
    if not ws:
        raise RuntimeError("provisioning completed but workspace not found")
    return ws


async def provision_via_browser_use(company: str, admin_email: str, plan: str, seats: int) -> dict:
    from browser_use import Agent
    from browser_use.llm import ChatGoogle

    llm = ChatGoogle(model=config.GEMINI_BROWSER_MODEL, api_key=config.GOOGLE_API_KEY)
    task = (
        f"Go to {ACME_ADMIN_URL}/admin/login. Log in with email '{config.ACME_ADMIN_USER}' and "
        f"password '{config.ACME_ADMIN_PASS}'. On the admin page, create a new workspace with "
        f"Company name '{company}', Admin email '{admin_email}', Plan '{plan}', and Seats '{seats}'. "
        f"Submit the form. Then stop."
    )
    agent = Agent(task=task, llm=llm)
    await agent.run(max_steps=15)
    ws = _fetch_workspace(company)
    if not ws:
        raise RuntimeError("browser-use finished but workspace not found")
    return ws


async def provision_workspace(company: str, admin_email: str, plan: str = "Growth",
                              seats: int = 10) -> dict:
    """Provision a customer workspace; return its details incl. the API key."""
    if PROVISION_MODE == "browser_use":
        try:
            return await provision_via_browser_use(company, admin_email, plan, seats)
        except Exception as e:  # noqa: BLE001
            log.warning("browser_use provisioning failed (%s); falling back to playwright", e)
    return await provision_via_playwright(company, admin_email, plan, seats)


if __name__ == "__main__":
    import sys
    args = dict(company="Globex Inc", admin_email="admin@globex.com", plan="Growth", seats=12)
    if len(sys.argv) > 1:
        args["company"] = sys.argv[1]
    print(asyncio.run(provision_workspace(**args)))
