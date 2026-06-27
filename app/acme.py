"""Mock "Acme" SaaS — a small but real-feeling B2B workspace product.

Two surfaces:
  - Vendor admin console (/acme/admin/*) — what the onboarding agent operates via
    browser-use: create a workspace, then on ONE workspace page invite members with
    roles, generate API keys, toggle features, and change plan.
  - Customer app (/acme/login, /acme/dashboard) — what the new customer logs into
    (member email + temporary password issued when invited).

Everything an agent needs is reachable in <=2 page hops with clearly-labelled forms,
so browser automation stays reliable. State is in-memory (resets on restart).
"""
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app import config

router = APIRouter(prefix="/acme", tags=["acme"])

WORKSPACES: dict[str, dict] = {}          # slug -> workspace
SESSION_COOKIE = "acme_session"
_SESSIONS: dict[str, dict] = {}            # token -> {"role","slug"}
PLANS = ["Starter", "Growth", "Enterprise"]
ROLES = ["Viewer", "Member", "Admin"]
FEATURES = ["SSO", "Audit log", "Webhooks"]


def _slug(name: str) -> str:
    return name.strip().lower().replace(" ", "-")


def _page(body: str, title: str = "Acme") -> HTMLResponse:
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1117;color:#e6e8ee;margin:0;padding:36px;}}
 .card{{max-width:820px;margin:0 auto 18px;background:#171a23;border:1px solid #262b38;border-radius:14px;padding:24px 28px;}}
 h1{{font-size:21px;margin:0 0 4px}} h2{{font-size:15px;margin:0 0 12px;color:#cdd3e0}}
 .sub{{color:#8b93a7;margin:0 0 18px;font-size:14px}}
 label{{display:block;font-size:12px;color:#aab2c5;margin:10px 0 5px}}
 input,select{{width:100%;padding:9px 11px;border-radius:8px;border:1px solid #2c3242;background:#0f1218;color:#e6e8ee;font-size:14px;box-sizing:border-box}}
 .row{{display:flex;gap:12px}} .row>div{{flex:1}}
 button{{margin-top:14px;background:#5b8cff;color:#fff;border:0;padding:10px 16px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}}
 button.sec{{background:#222838;color:#cdd3e0}}
 table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}}
 th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #232838}}
 code{{background:#0b0d12;padding:2px 6px;border-radius:5px;color:#8fd0ff;font-size:12px}}
 .pill{{font-size:11px;padding:2px 9px;border-radius:20px;background:#1f2a44;color:#9bc1ff}}
 .on{{background:#15351f;color:#7ee29a}} .off{{background:#2a1f1f;color:#e29a9a}}
 .logo{{font-weight:800;letter-spacing:-.5px;color:#5b8cff;font-size:15px;margin-bottom:16px}}
 a{{color:#7fb0ff}} .chk{{display:flex;align-items:center;gap:8px;margin:8px 0}} .chk input{{width:auto}}
</style></head><body><div class="logo">▲ ACME</div>{body}</body></html>"""
    return HTMLResponse(html)


def _sess(req: Request):
    return _SESSIONS.get(req.cookies.get(SESSION_COOKIE))


def _set_sess(data: dict, to: str):
    token = secrets.token_urlsafe(24)
    _SESSIONS[token] = data
    r = RedirectResponse(to, status_code=status.HTTP_303_SEE_OTHER)
    r.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax")
    return r


# ============================ Vendor admin console ============================
@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page():
    return _page("""<div class="card"><h1>Sign in to Acme</h1><p class="sub">Internal admin console</p>
    <form method="post" action="/acme/admin/login">
      <label>Email</label><input name="email" placeholder="admin@acme.test">
      <label>Password</label><input name="password" type="password">
      <button type="submit">Sign in</button></form></div>""", "Acme — Admin")


@router.post("/admin/login")
def admin_login(email: str = Form(...), password: str = Form(...)):
    if email.strip() == config.ACME_ADMIN_USER and password == config.ACME_ADMIN_PASS:
        return _set_sess({"role": "admin", "slug": None}, "/acme/admin")
    return _page('<div class="card"><h1>Sign in failed</h1><a href="/acme/admin/login">Try again</a></div>')


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    rows = "".join(
        f"<tr><td><a href='/acme/admin/ws/{w['slug']}'>{w['company']}</a></td>"
        f"<td><span class='pill'>{w['plan']}</span></td><td>{len(w['members'])}</td>"
        f"<td>{len(w['api_keys'])}</td></tr>" for w in WORKSPACES.values())
    rows = rows or "<tr><td colspan=4 style='color:#6b7280'>No workspaces yet.</td></tr>"
    opts = "".join(f"<option>{p}</option>" for p in PLANS)
    return _page(f"""
    <div class="card"><h1>Create workspace</h1><p class="sub">Provision a new customer</p>
      <form method="post" action="/acme/admin/create">
        <label>Company name</label><input name="company" placeholder="Globex Inc" required>
        <div class="row"><div><label>Plan</label><select name="plan">{opts}</select></div>
          <div><label>Seats</label><input name="seats" type="number" value="10"></div></div>
        <button type="submit">Create workspace</button></form></div>
    <div class="card"><h2>Workspaces</h2>
      <table><thead><tr><th>Company</th><th>Plan</th><th>Members</th><th>API keys</th></tr></thead>
      <tbody>{rows}</tbody></table></div>""", "Acme — Admin")


@router.post("/admin/create")
def admin_create(request: Request, company: str = Form(...), plan: str = Form("Starter"),
                 seats: int = Form(10)):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    slug = _slug(company)
    WORKSPACES[slug] = {
        "company": company.strip(), "slug": slug, "plan": plan, "seats": int(seats),
        "members": [], "api_keys": [], "features": {f: False for f in FEATURES},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return RedirectResponse(f"/acme/admin/ws/{slug}", status_code=303)


@router.get("/admin/ws/{slug}", response_class=HTMLResponse)
def admin_ws(request: Request, slug: str):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    w = WORKSPACES.get(slug)
    if not w:
        return RedirectResponse("/acme/admin", status_code=303)
    members = "".join(
        f"<tr><td>{m['email']}</td><td><span class='pill'>{m['role']}</span></td>"
        f"<td><code>{m['password']}</code></td></tr>" for m in w["members"]
    ) or "<tr><td colspan=3 style='color:#6b7280'>No members yet.</td></tr>"
    keys = "".join(
        f"<tr><td><code>{k['key']}</code></td><td>{k['label']}</td></tr>" for k in w["api_keys"]
    ) or "<tr><td colspan=2 style='color:#6b7280'>No API keys yet.</td></tr>"
    role_opts = "".join(f"<option>{r}</option>" for r in ROLES)
    plan_opts = "".join(f"<option {'selected' if p==w['plan'] else ''}>{p}</option>" for p in PLANS)
    feats = "".join(
        f"<div class='chk'><input type='checkbox' name='{f}' {'checked' if w['features'][f] else ''}>"
        f"<span>{f}</span></div>" for f in FEATURES)
    return _page(f"""
    <div class="card"><h1>{w['company']}</h1>
      <p class="sub"><span class="pill">{w['plan']}</span> · {w['seats']} seats · <a href="/acme/admin">← all workspaces</a></p></div>

    <div class="card"><h2>Members</h2>
      <table><thead><tr><th>Email</th><th>Role</th><th>Temp password</th></tr></thead><tbody>{members}</tbody></table>
      <form method="post" action="/acme/admin/ws/{slug}/invite" style="margin-top:14px">
        <div class="row"><div><label>Invite email</label><input name="email" placeholder="person@globex.com" required></div>
          <div><label>Role</label><select name="role">{role_opts}</select></div></div>
        <button type="submit">Invite member</button></form></div>

    <div class="card"><h2>API keys</h2>
      <table><thead><tr><th>Key</th><th>Label</th></tr></thead><tbody>{keys}</tbody></table>
      <form method="post" action="/acme/admin/ws/{slug}/apikey" style="margin-top:14px">
        <label>Label</label><input name="label" placeholder="Production">
        <button type="submit">Generate API key</button></form></div>

    <div class="card"><h2>Features</h2>
      <form method="post" action="/acme/admin/ws/{slug}/features">{feats}
        <button type="submit">Save features</button></form></div>

    <div class="card"><h2>Plan</h2>
      <form method="post" action="/acme/admin/ws/{slug}/plan">
        <label>Plan</label><select name="plan">{plan_opts}</select>
        <button type="submit">Update plan</button></form></div>
    """, f"Acme — {w['company']}")


@router.post("/admin/ws/{slug}/invite")
def admin_invite(request: Request, slug: str, email: str = Form(...), role: str = Form("Member")):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    w = WORKSPACES.get(slug)
    if w:
        w["members"].append({"email": email.strip(), "role": role,
                             "password": secrets.token_urlsafe(6)})
    return RedirectResponse(f"/acme/admin/ws/{slug}", status_code=303)


@router.post("/admin/ws/{slug}/apikey")
def admin_apikey(request: Request, slug: str, label: str = Form("default")):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    w = WORKSPACES.get(slug)
    if w:
        w["api_keys"].append({"key": "acme_live_" + secrets.token_hex(16),
                              "label": label or "default",
                              "created_at": datetime.now(timezone.utc).isoformat()})
    return RedirectResponse(f"/acme/admin/ws/{slug}", status_code=303)


@router.post("/admin/ws/{slug}/features")
async def admin_features(request: Request, slug: str):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    w = WORKSPACES.get(slug)
    if w:
        form = await request.form()
        for f in FEATURES:
            w["features"][f] = f in form
    return RedirectResponse(f"/acme/admin/ws/{slug}", status_code=303)


@router.post("/admin/ws/{slug}/plan")
def admin_plan(request: Request, slug: str, plan: str = Form(...)):
    if not (_sess(request) or {}).get("role") == "admin":
        return RedirectResponse("/acme/admin/login", status_code=303)
    w = WORKSPACES.get(slug)
    if w:
        w["plan"] = plan
    return RedirectResponse(f"/acme/admin/ws/{slug}", status_code=303)


# ============================== Customer app =================================
@router.get("/", response_class=HTMLResponse)
@router.get("/login", response_class=HTMLResponse)
def customer_login_page():
    return _page("""<div class="card"><h1>Sign in to your workspace</h1>
    <p class="sub">Use the email and temporary password from your welcome email.</p>
    <form method="post" action="/acme/login">
      <label>Email</label><input name="email">
      <label>Password</label><input name="password" type="password">
      <button type="submit">Sign in</button></form></div>""", "Acme")


def _find_member(email: str, password: str):
    for w in WORKSPACES.values():
        for m in w["members"]:
            if m["email"].lower() == email.strip().lower() and m["password"] == password:
                return w, m
    return None, None


@router.post("/login")
def customer_login(email: str = Form(...), password: str = Form(...)):
    w, m = _find_member(email, password)
    if w:
        return _set_sess({"role": "customer", "slug": w["slug"], "email": m["email"]}, "/acme/dashboard")
    return _page('<div class="card"><h1>Sign in failed</h1><a href="/acme/login">Try again</a></div>')


@router.get("/dashboard", response_class=HTMLResponse)
def customer_dashboard(request: Request):
    s = _sess(request)
    if not s or s.get("role") != "customer":
        return RedirectResponse("/acme/login", status_code=303)
    w = WORKSPACES.get(s["slug"])
    if not w:
        return RedirectResponse("/acme/login", status_code=303)
    members = "".join(f"<tr><td>{m['email']}</td><td><span class='pill'>{m['role']}</span></td></tr>"
                      for m in w["members"]) or "<tr><td colspan=2>—</td></tr>"
    keys = "".join(f"<tr><td><code>{k['key']}</code></td><td>{k['label']}</td></tr>"
                   for k in w["api_keys"]) or "<tr><td colspan=2 style='color:#6b7280'>None yet</td></tr>"
    feats = "".join(f"<span class='pill {'on' if v else 'off'}'>{f} {'on' if v else 'off'}</span> "
                    for f, v in w["features"].items())
    return _page(f"""
    <div class="card"><h1>{w['company']} workspace</h1>
      <p class="sub">Signed in as {s['email']} · <span class="pill">{w['plan']}</span> · {w['seats']} seats</p>
      <div>{feats}</div></div>
    <div class="card"><h2>Team</h2><table><thead><tr><th>Email</th><th>Role</th></tr></thead>
      <tbody>{members}</tbody></table></div>
    <div class="card"><h2>API keys</h2><table><thead><tr><th>Key</th><th>Label</th></tr></thead>
      <tbody>{keys}</tbody></table></div>""", "Acme — Dashboard")


# ================================== API =====================================
@router.get("/api/workspaces")
def api_workspaces():
    return JSONResponse({"workspaces": list(WORKSPACES.values())})


@router.get("/api/workspaces/{slug}")
def api_workspace(slug: str):
    w = WORKSPACES.get(slug)
    return JSONResponse(w) if w else JSONResponse({"error": "not found"}, status_code=404)
