"""Resend email sending (HTTP API, no SDK dependency)."""
import httpx

from app import config


def send_email(to: str, subject: str, html: str, from_addr: str | None = None) -> dict:
    payload = {
        "from": from_addr or config.RESEND_FROM,
        "to": to,
        "subject": subject,
        "html": html,
    }
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def welcome_email_html(customer_name: str, company: str, plan: str, seats: int,
                       api_key: str, dashboard_url: str, admin_email: str) -> str:
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:540px;margin:0 auto;color:#0f172a">
      <h2 style="margin:0 0 8px">You're all set, {customer_name} 🎉</h2>
      <p>Your <b>{company}</b> workspace is live on the <b>{plan}</b> plan ({seats} seats).
         An admin invite has been sent to <b>{admin_email}</b>.</p>
      <div style="background:#0f1117;color:#e6e8ee;border-radius:10px;padding:18px 20px;margin:20px 0">
        <div style="font-size:12px;color:#8b93a7;margin-bottom:6px">YOUR API KEY</div>
        <code style="font-size:14px;color:#8fd0ff;word-break:break-all">{api_key}</code>
      </div>
      <p style="margin:24px 0">
        <a href="{dashboard_url}" style="background:#5b8cff;color:#fff;text-decoration:none;
           padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block">
           Open your dashboard →</a>
      </p>
      <p style="color:#64748b;font-size:13px">Dashboard: {dashboard_url}<br>
         Keep your API key somewhere safe — it's also shown in your dashboard.</p>
    </div>"""


def scheduling_email_html(customer_name: str, company: str, call_url: str,
                          context_line: str = "") -> str:
    ctx = f"<p style='color:#475569'>{context_line}</p>" if context_line else ""
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;color:#0f172a">
      <h2 style="margin:0 0 8px">Welcome to Acme, {customer_name} 👋</h2>
      <p>Congratulations on getting started — we're excited to have {company} on board.</p>
      {ctx}
      <p>I'm your onboarding assistant. To get you set up, let's hop on a quick voice call —
         I'll provision your workspace and walk you through everything live.</p>
      <p style="margin:28px 0">
        <a href="{call_url}" style="background:#5b8cff;color:#fff;text-decoration:none;
           padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block">
           Start onboarding call →</a>
      </p>
      <p style="color:#64748b;font-size:13px">Or paste this link into your browser:<br>{call_url}</p>
    </div>"""
