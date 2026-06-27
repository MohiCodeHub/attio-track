"""Mock "Acme" SaaS product with a real admin panel.

This is the target system the onboarding agent operates via browser-use:
log in, create a workspace, set its plan, invite a user, generate an API key.
State is in-memory (resets on restart) — fine for a demo.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app import config

router = APIRouter(prefix="/acme", tags=["acme"])

# In-memory store: workspace_slug -> dict
WORKSPACES: dict[str, dict] = {}
SESSION_COOKIE = "acme_session"
_SESSIONS: set[str] = set()

PLANS = ["Starter", "Growth", "Enterprise"]


def _page(body: str, title: str = "Acme Admin") -> HTMLResponse:
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1117;color:#e6e8ee;margin:0;padding:40px;}}
 .card{{max-width:760px;margin:0 auto;background:#171a23;border:1px solid #262b38;border-radius:14px;padding:28px 32px;}}
 h1{{font-size:22px;margin:0 0 4px}} .sub{{color:#8b93a7;margin:0 0 24px;font-size:14px}}
 label{{display:block;font-size:13px;color:#aab2c5;margin:14px 0 6px}}
 input,select{{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #2c3242;background:#0f1218;color:#e6e8ee;font-size:14px;box-sizing:border-box}}
 button{{margin-top:20px;background:#5b8cff;color:#fff;border:0;padding:11px 18px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}}
 table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}}
 th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #232838}}
 code{{background:#0b0d12;padding:2px 6px;border-radius:5px;color:#8fd0ff;font-size:12px}}
 .pill{{font-size:11px;padding:2px 8px;border-radius:20px;background:#243; color:#9be6a8}}
 .logo{{font-weight:800;letter-spacing:-.5px;color:#5b8cff;font-size:15px;margin-bottom:18px}}
</style></head><body><div class="card"><div class="logo">▲ ACME</div>{body}</div></body></html>"""
    return HTMLResponse(html)


def _authed(request: Request) -> bool:
    return request.cookies.get(SESSION_COOKIE) in _SESSIONS


@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
def login_page():
    body = """
    <h1>Sign in to Acme</h1>
    <p class="sub">Admin console</p>
    <form method="post" action="/acme/login">
      <label>Email</label><input name="email" type="email" placeholder="admin@acme.test" autocomplete="username">
      <label>Password</label><input name="password" type="password" autocomplete="current-password">
      <button type="submit">Sign in</button>
    </form>"""
    return _page(body, "Acme — Sign in")


@router.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    if email.strip() == config.ACME_ADMIN_USER and password == config.ACME_ADMIN_PASS:
        token = secrets.token_urlsafe(24)
        _SESSIONS.add(token)
        resp = RedirectResponse("/acme/admin", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return resp
    return _page('<h1>Sign in failed</h1><p class="sub">Invalid credentials.</p>'
                 '<a href="/acme/login" style="color:#5b8cff">Try again</a>', "Acme — Error")


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not _authed(request):
        return RedirectResponse("/acme/login", status_code=status.HTTP_303_SEE_OTHER)
    rows = ""
    for slug, w in WORKSPACES.items():
        rows += (f"<tr><td>{w['company']}</td><td><span class='pill'>{w['plan']}</span></td>"
                 f"<td>{w['seats']}</td><td><code>{w['api_key']}</code></td>"
                 f"<td>{'✓' if w['admin_invited'] else '—'}</td></tr>")
    if not rows:
        rows = "<tr><td colspan='5' style='color:#6b7280'>No workspaces yet.</td></tr>"
    options = "".join(f"<option>{p}</option>" for p in PLANS)
    body = f"""
    <h1>Workspaces</h1>
    <p class="sub">Provision a customer workspace</p>
    <form method="post" action="/acme/admin/provision">
      <label>Company name</label><input name="company" placeholder="Globex Inc" required>
      <label>Admin email (to invite)</label><input name="admin_email" type="email" placeholder="admin@globex.com" required>
      <label>Plan</label><select name="plan">{options}</select>
      <label>Seats</label><input name="seats" type="number" value="10" min="1">
      <button type="submit">Create workspace &amp; generate API key</button>
    </form>
    <h1 style="font-size:16px;margin-top:30px">Existing</h1>
    <table><thead><tr><th>Company</th><th>Plan</th><th>Seats</th><th>API key</th><th>Admin invited</th></tr></thead>
    <tbody>{rows}</tbody></table>"""
    return _page(body, "Acme — Admin")


@router.post("/admin/provision")
def provision(
    request: Request,
    company: str = Form(...),
    admin_email: str = Form(...),
    plan: str = Form("Starter"),
    seats: int = Form(10),
):
    if not _authed(request):
        return RedirectResponse("/acme/login", status_code=status.HTTP_303_SEE_OTHER)
    slug = company.strip().lower().replace(" ", "-")
    api_key = "acme_live_" + secrets.token_hex(16)
    WORKSPACES[slug] = {
        "company": company.strip(),
        "slug": slug,
        "plan": plan,
        "seats": int(seats),
        "admin_email": admin_email.strip(),
        "admin_invited": True,
        "api_key": api_key,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return RedirectResponse("/acme/admin", status_code=status.HTTP_303_SEE_OTHER)


# --- tiny JSON API for verification / agent confirmation ---
@router.get("/api/workspaces")
def api_workspaces():
    return JSONResponse({"workspaces": list(WORKSPACES.values())})


@router.get("/api/workspaces/{slug}")
def api_workspace(slug: str):
    w = WORKSPACES.get(slug)
    if not w:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(w)
