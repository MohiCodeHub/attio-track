"""One-time Attio setup for the demo. Run AFTER enabling the Deals object.

  python -m scripts.seed_attio

Creates the `onboarding_status` status attribute on Deals, plus a demo
company + person + deal (stage 'Lead') you can flip to 'Won 🎉' to fire the loop.
"""
import sys
import httpx

from app import config

H = {"Authorization": f"Bearer {config.ATTIO_API_KEY}", "Content-Type": "application/json"}
B = config.ATTIO_BASE


def call(method, path, body=None):
    r = httpx.request(method, B + path, headers=H, json=body, timeout=30)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)


def main():
    # 0) deals enabled?
    s, d = call("GET", "/objects/deals")
    if s != 200:
        print("❌ Deals object not available. Enable it in Attio (Settings → Objects → Deals), then re-run.")
        print("   API said:", d)
        sys.exit(1)
    print("✓ Deals object enabled")

    # 1) onboarding_status attribute (idempotent)
    s, d = call("POST", "/objects/deals/attributes", {"data": {
        "title": "Onboarding Status", "api_slug": "onboarding_status", "type": "status",
        "description": "Autonomous onboarding agent state",
        "is_required": False, "is_unique": False, "is_multiselect": False,
    }})
    print("onboarding_status attribute:", "created ✓" if s < 300 else f"exists/skip ({s})")
    # status options must be created via the dedicated statuses API (not inline)
    for title in ["Pending", "Scheduled", "Provisioning", "Activated", "Escalated"]:
        call("POST", "/objects/deals/attributes/onboarding_status/statuses",
             {"data": {"title": title}})
    print("onboarding_status options ensured ✓")

    # 2) demo company
    s, d = call("POST", "/objects/companies/records", {"data": {"values": {
        "name": "Globex Inc", "domains": [{"domain": "globex.com"}]}}})
    company_id = d["data"]["id"]["record_id"] if s < 300 else None
    print("company Globex Inc:", company_id or f"err {s} {str(d)[:120]}")

    # 3) demo person
    s, d = call("POST", "/objects/people/records", {"data": {"values": {
        "name": [{"first_name": "Sam", "last_name": "Rivera", "full_name": "Sam Rivera"}],
        "email_addresses": [{"email_address": config.DEMO_CUSTOMER_EMAIL}]}}})
    person_id = d["data"]["id"]["record_id"] if s < 300 else None
    print("person Sam Rivera:", person_id or f"err {s} {str(d)[:120]}")

    # 4) demo deal (stage Lead) — owner is required (actor-reference -> workspace member)
    s_me, me = call("GET", "/self")
    member_id = me.get("authorized_by_workspace_member_id")
    values = {
        "name": "Globex — Annual",
        "stage": "Lead",
        "owner": [{"referenced_actor_type": "workspace-member", "referenced_actor_id": member_id}],
        "value": 24000,
    }
    if company_id:
        values["associated_company"] = [{"target_object": "companies", "target_record_id": company_id}]
    if person_id:
        values["associated_people"] = [{"target_object": "people", "target_record_id": person_id}]
    s, d = call("POST", "/objects/deals/records", {"data": {"values": values}})
    if s < 300:
        deal = d["data"]
        rid = deal["id"]["record_id"]
        print("\n✅ Demo deal created")
        print("   record_id:", rid)
        print("   web_url:  ", deal.get("web_url"))
        print("\nNext: in Attio, move this deal's Stage to 'Won 🎉' (or POST it to /webhooks/attio with")
        print(f'   {{"record_id":"{rid}"}} to test the loop without the workflow).')
    else:
        print("deal err", s, str(d)[:200])


if __name__ == "__main__":
    main()
