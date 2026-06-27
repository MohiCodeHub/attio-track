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
