"""Pre-call company research via Gemini with Google Search grounding.

Produces one short, tailored sentence used in the scheduling email and given
to the voice agent as context. Best-effort: returns "" on any failure.
"""
import httpx

from app import config


def company_briefing_line(company: str) -> str:
    if not company or company.lower() in ("your company", ""):
        return ""
    prompt = (
        f"In ONE short sentence (max 25 words), say something specific and useful about the "
        f"company '{company}' that would help tailor a SaaS onboarding call (their industry, "
        f"what they do, or recent news). If you don't know them, return an empty string."
    )
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_PLAN_MODEL}:generateContent?key={config.GOOGLE_API_KEY}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
    }
    try:
        r = httpx.post(url, json=body, timeout=25)
        r.raise_for_status()
        d = r.json()
        text = d["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text if len(text) > 3 else ""
    except Exception:
        return ""
