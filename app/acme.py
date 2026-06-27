"""Mock "Acme" SaaS product.

Two surfaces:
  - Vendor admin console (/acme/admin/*) — internal; what the onboarding agent
    operates via browser-use to provision a customer (login: ACME_ADMIN_USER/PASS).
  - Customer app (/acme/login, /acme/dashboard) — what the new customer logs into
    with the per-customer credentials issued during provisioning.

State is in-memory (resets on restart) — fine for a demo.
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app import config

router = APIRouter(prefix="/acme", tags=["acme"])

# workspace_slug -> dict
WORKSPACES: dict[str, dict] = {}
SESSION_COOKIE = "acme_session"
_SESSIONS: dict[str, dict] = {}   # token -> {"role": "admin"|"customer", "slug": str|None}
PLANS = ["Starter", "Growth", "Enterprise"]


def _page(body: str, title: str = "Acme", subtitle: str = "") -> HTMLResponse:
    sub = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title><meta name="viewport" content="width=device-width, initial-scale=1">
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
 .pill{{font-size:11px;padding:2px 8px;border-radius:20px;background:#243;color:#9be6a8}}
 .logo{{font-weight:800;letter-spacing:-.5px;color:#5b8cff;font-size:15px;margin-bottom:18px}}
 .kv{{background:#0f1218;border:1px solid #232838;border-radius:10px;padding:14px 16px;margin:12px 0}}
 .kv .k{{font-size:12px;color:#8b93a7}} .kv .v{{font-size:15px;margin-top:2px}}
</style></head><body><div class="card"><div class="logo">▲ ACME</div>{body}{sub if False else ""}</div></body></html>"""
    return HTMLResponse(html)


def _new_session(data: dict) -> str:
    token = secrets.token_urlsafe(24)
    _SESSIONS[token] = data
    return token


def _session(request: Request) -> dict | None:
    return _SESSIONS.get(request.cookies.get(SESSION_COOKIE))


# ============================ Vendor admin console ============================
@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    body = """
    <h1>Sign in to Acme</h1><p class="sub">Internal admin console</p>
    <form method="post" action="/acme/admin/login">
      <label>Email</label><input name="email" type="email" placeholder="admin@acme.test" autocomplete="username">
      <label>Password</label><input name="password" type="password" autocomplete="current-password">
      <button type="submit">Sign in</button>
    </form>"""
    return _page(body, "Acme — Admin")


@router.post("/admin/login")
def admin_login(email: str = Form(...), password: str = Form(...)):
    if email.strip() == config.ACME_ADMIN_USER and password == config.ACME_ADMIN_PASS:
        token = _new_session({"role": "admin", "slug": None})
        resp = RedirectResponse("/acme/admin", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
        return resp
    return _page('<h1>Sign in failed</h1><p class="sub">Invalid admin credentials.</p>'
                 '<a href="/acme/admin/login" style="color:#5b8cff">Try again</a>', "Acme — Error")


@router.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    s = _session(request)
    if not s or s.get("role") != "admin":
        return RedirectResponse("/acme/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    rows = ""
    for w in WORKSPACES.values():
        rows += (f"<tr><td>{w['company']}</td><td><span class='pill'>{w['plan']}</span></td>"
                 f"<td>{w['seats']}</td><td>{w['login_email']}</td><td><code>{w['api_key']}</code></td></tr>")
    if not rows:
        rows = "<tr><td colspan='5' style='color:#6b7280'>No workspaces yet.</td></tr>"
    options = "".join(f"<option>{p}</option>" for p in PLANS)
    body = f"""
    <h1>Workspaces</h1><p class="sub">Provision a customer workspace</p>
    <form method="post" action="/acme/admin/provision">
      <label>Company name</label><input name="company" placeholder="Globex Inc" required>
      <label>Admin email (becomes the customer login)</label><input name="admin_email" type="email" placeholder="admin@globex.com" required>
      <label>Plan</label><select name="plan">{options}</select>
      <label>Seats</label><input name="seats" type="number" value="10" min="1">
      <button type="submit">Create workspace &amp; generate API key</button>
    </form>
    <h1 style="font-size:16px;margin-top:30px">Existing</h1>
    <table><thead><tr><th>Company</th><th>Plan</th><th>Seats</th><th>Customer login</th><th>API key</th></tr></thead>
    <tbody>{rows}</tbody></table>"""
    return _page(body, "Acme — Admin")


@router.post("/admin/provision")
def provision(request: Request, company: str = Form(...), admin_email: str = Form(...),
              plan: str = Form("Starter"), seats: int = Form(10)):
    s = _session(request)
    if not s or s.get("role") != "admin":
        return RedirectResponse("/acme/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    slug = company.strip().lower().replace(" ", "-")
    WORKSPACES[slug] = {
        "company": company.strip(), "slug": slug, "plan": plan, "seats": int(seats),
        "admin_email": admin_email.strip(),
        "login_email": admin_email.strip(),
        "password": secrets.token_urlsafe(6),   # temporary customer password
        "api_key": "acme_live_" + secrets.token_hex(16),
        "admin_invited": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return RedirectResponse("/acme/admin", status_code=status.HTTP_303_SEE_OTHER)


# ============================== Customer app =================================
@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
def customer_login_page():
    body = """
    <h1>Sign in to your workspace</h1><p class="sub">Use the email and temporary password from your welcome email.</p>
    <form method="post" action="/acme/login">
      <label>Email</label><input name="email" type="email" autocomplete="username">
      <label>Password</label><input name="password" type="password" autocomplete="current-password">
      <button type="submit">Sign in</button>
    </form>"""
    return _page(body, "Acme")


@router.post("/login")
def customer_login(email: str = Form(...), password: str = Form(...)):
    for w in WORKSPACES.values():
        if w["login_email"].lower() == email.strip().lower() and w["password"] == password:
            token = _new_session({"role": "customer", "slug": w["slug"]})
            resp = RedirectResponse("/acme/dashboard", status_code=status.HTTP_303_SEE_OTHER)
            resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
            return resp
    return _page('<h1>Sign in failed</h1><p class="sub">Wrong email or password.</p>'
                 '<a href="/acme/login" style="color:#5b8cff">Try again</a>', "Acme")


@router.get("/dashboard", response_class=HTMLResponse)
def customer_dashboard(request: Request):
    s = _session(request)
    if not s or s.get("role") != "customer":
        return RedirectResponse("/acme/login", status_code=status.HTTP_303_SEE_OTHER)
    w = WORKSPACES.get(s["slug"])
    if not w:
        return RedirectResponse("/acme/login", status_code=status.HTTP_303_SEE_OTHER)
    body = f"""
    <h1>{w['company']} workspace</h1><p class="sub">Welcome — you're all set up.</p>
    <div class="kv"><div class="k">PLAN</div><div class="v">{w['plan']} · {w['seats']} seats</div></div>
    <div class="kv"><div class="k">API KEY</div><div class="v"><code>{w['api_key']}</code></div></div>
    <div class="kv"><div class="k">SIGNED IN AS</div><div class="v">{w['login_email']}</div></div>
    <p class="sub" style="margin-top:20px">Next: invite your team and drop the API key into your integration.</p>"""
    return _page(body, "Acme — Dashboard")


# ================================== API =====================================
@router.get("/api/workspaces")
def api_workspaces():
    return JSONResponse({"workspaces": list(WORKSPACES.values())})


@router.get("/api/workspaces/{slug}")
def api_workspace(slug: str):
    w = WORKSPACES.get(slug)
    return JSONResponse(w) if w else JSONResponse({"error": "not found"}, status_code=404)
