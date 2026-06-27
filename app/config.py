"""Central config — loads .env once and exposes typed settings."""
import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# Attio
ATTIO_API_KEY = _get("ATTIO_API_KEY")
ATTIO_BASE = "https://api.attio.com/v2"

# Google Gemini
GOOGLE_API_KEY = _get("GOOGLE_API_KEY")
GEMINI_VOICE_MODEL = _get("GEMINI_VOICE_MODEL", "gemini-3.5-flash")
GEMINI_PLAN_MODEL = _get("GEMINI_PLAN_MODEL", "gemini-3.5-flash")
GEMINI_BROWSER_MODEL = _get("GEMINI_BROWSER_MODEL", "gemini-3.5-flash")

# SLNG
SLNG_API_KEY = _get("SLNG_API_KEY")
SLNG_BASE = "https://api.slng.ai"
SLNG_STT_MODEL = _get("SLNG_STT_MODEL", "deepgram/nova:3")
SLNG_TTS_MODEL = _get("SLNG_TTS_MODEL", "deepgram/aura:2")

# LiveKit
LIVEKIT_URL = _get("LIVEKIT_URL")
LIVEKIT_API_KEY = _get("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = _get("LIVEKIT_API_SECRET")

# Resend
RESEND_API_KEY = _get("RESEND_API_KEY")
RESEND_FROM = _get("RESEND_FROM", "onboarding@resend.dev")
# Resend sandbox can only deliver to the account owner address until a domain is verified.
DEMO_CUSTOMER_EMAIL = _get("DEMO_CUSTOMER_EMAIL", "mohammad.atif@outlook.com")

# Acme mock product admin (target of browser-use provisioning)
ACME_ADMIN_USER = _get("ACME_ADMIN_USER", "admin@acme.test")
ACME_ADMIN_PASS = _get("ACME_ADMIN_PASS", "acme-admin-pass")

# Public base URL of THIS service (Render URL in prod, tunnel locally).
# Used to build the call link sent in the scheduling email.
PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL", "http://localhost:8000")
