"""Create (or replace) the Attio webhook that fires the onboarding loop.

Usage:
  python -m scripts.create_webhook https://<your-render-url>

Subscribes to record.updated on the Deals object's `stage` attribute and points
it at <url>/webhooks/attio. The handler then filters to stage == 'Won 🎉' and is
idempotent, so a broad subscription is safe.
"""
import sys
import httpx

from app import config

H = {"Authorization": f"Bearer {config.ATTIO_API_KEY}", "Content-Type": "application/json"}
B = config.ATTIO_BASE


def main():
    if len(sys.argv) < 2:
        print("usage: python -m scripts.create_webhook https://<render-url>")
        sys.exit(1)
    base = sys.argv[1].rstrip("/")
    target = f"{base}/webhooks/attio"

    # Remove any existing webhooks pointing at this path (idempotent re-run).
    existing = httpx.get(f"{B}/webhooks", headers=H, timeout=30).json().get("data", [])
    for w in existing:
        if w.get("target_url", "").rstrip("/").endswith("/webhooks/attio"):
            wid = w["id"]["webhook_id"]
            httpx.delete(f"{B}/webhooks/{wid}", headers=H, timeout=30)
            print("removed old webhook", wid)

    # Attio requires `filter` to be present; null = all record.updated events.
    # Our handler filters to deals + stage 'Won 🎉' and is idempotent, so this is safe.
    body = {"data": {
        "target_url": target,
        "subscriptions": [
            {"event_type": "record.updated", "filter": None},
        ],
    }}
    r = httpx.post(f"{B}/webhooks", headers=H, json=body, timeout=30)
    if r.status_code >= 300:
        print("❌ create failed", r.status_code, r.text[:400])
        sys.exit(1)
    d = r.json()["data"]
    print("✅ webhook created")
    print("   id:        ", d["id"]["webhook_id"])
    print("   target_url:", target)
    print("   secret:    ", d.get("secret", "(none returned)"))
    print("\nNow flip the demo deal's Stage to 'Won 🎉' in Attio to fire the loop.")


if __name__ == "__main__":
    main()
