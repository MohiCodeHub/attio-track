"""Reset to a clean demo state before each take.

  python -m scripts.reset_demo

- Sets the demo deal back to stage 'Lead' / onboarding_status 'Pending' (so the
  Won-trigger guard will fire fresh).
- Clears the Acme product (workspaces) at PUBLIC_BASE_URL so provisioning shows
  the browser creating everything from scratch.
"""
import httpx

from app import attio, config

DEMO_DEAL = "598770d5-7ec1-474b-ba4c-18b0fe10cd42"


def main():
    attio.update_record("deals", DEMO_DEAL,
                        {"stage": "Lead", "onboarding_status": "Pending"})
    print("✓ deal reset: stage=Lead, onboarding_status=Pending")
    try:
        r = httpx.post(f"{config.PUBLIC_BASE_URL}/acme/reset", timeout=30)
        print(f"✓ Acme cleared at {config.PUBLIC_BASE_URL} ({r.status_code})")
    except Exception as e:  # noqa: BLE001
        print(f"! could not clear Acme at {config.PUBLIC_BASE_URL}: {e}")


if __name__ == "__main__":
    main()
