"""Phase 4 -- Gmail filters, the part that keeps it fixed.

Filter sets are generated into config/filters.<account>.json so they are
versioned in git and re-runnable. Applying is idempotent: every existing filter
is reduced to a signature and matching ones are skipped, so running this twice
does not produce two copies of anything.

Actions are stored as label *names*, not ids. Label ids differ between the two
accounts, so a name-based config is the only form that survives being applied
to both.

Note for the report: Gmail filters only act on **incoming** mail. They do
nothing to the existing backlog, which is precisely why Phases 2 and 3 exist.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .cleanup import DOMAIN_QUERY_CHUNK

BUSINESS_ADDRESS = "james@intersectionstrategies.co"


def _chunks(items: list[str], size: int = DOMAIN_QUERY_CHUNK) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _from_clause(domains: list[str]) -> str:
    """Gmail stores multi-domain sender criteria as 'a.com OR b.com'."""
    return " OR ".join(domains)


def build_personal(config: dict, derived_newsletters: list[tuple[str, str]]) -> dict:
    p = config["personal"]
    seed_news = list(p["newsletters"])
    derived = [d for d, _ in derived_newsletters if d not in seed_news]
    reasons = dict(derived_newsletters)

    filters: list[dict] = []

    for i, chunk in enumerate(_chunks(seed_news), 1):
        filters.append({
            "key": f"personal.newsletters.seed.{i}",
            "description": f"Newsletters ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Newsletters and skip the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Newsletters"], "removeLabelIds": ["INBOX"]},
            "source": "seed",
        })

    for i, chunk in enumerate(_chunks(derived), 1):
        filters.append({
            "key": f"personal.newsletters.derived.{i}",
            "description": f"Newsletters detected from your own 90-day data "
                           f"({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Newsletters and skip the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Newsletters"], "removeLabelIds": ["INBOX"]},
            "source": "derived",
            "why": {d: reasons[d] for d in chunk},
        })

    for i, chunk in enumerate(_chunks(p["promotional"]), 1):
        filters.append({
            "key": f"personal.promotional.{i}",
            "description": f"Retail and promotional senders "
                           f"({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) → skip the inbox "
                           f"and mark as read",
            #  Removing UNREAD is Gmail's "Mark as read" filter action. Without
            #  it these quietly rebuild the unread pile the badge kill cleared.
            "criteria": {"from": _from_clause(chunk)},
            "action": {"removeLabelIds": ["INBOX", "UNREAD"]},
            "source": "seed",
        })

    for i, chunk in enumerate(_chunks(p["banks"]), 1):
        filters.append({
            "key": f"personal.banks.{i}",
            "description": f"Card and bank alerts ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Finances, stay in the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Finances"]},
            "source": "seed",
        })

    filters.append({
        "key": "personal.is_address",
        "description": f"Anything addressed to {BUSINESS_ADDRESS} that lands "
                       f"here → label IS, stay in the inbox",
        "criteria": {"to": BUSINESS_ADDRESS},
        "action": {"addLabelNames": ["IS"]},
        "source": "seed",
    })

    return _wrap("personal", filters)


def build_business(config: dict, derived_newsletters: list[tuple[str, str]]) -> dict:
    b = config["business"]
    seed_news = list(b["newsletters"])
    derived = [d for d, _ in derived_newsletters if d not in seed_news]
    reasons = dict(derived_newsletters)

    filters: list[dict] = []

    for i, chunk in enumerate(_chunks(b["receipts"]), 1):
        filters.append({
            "key": f"business.receipts.{i}",
            "description": f"Payment and receipt senders ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label IS/Receipts 2026, stay in the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["IS/Receipts 2026"]},
            "source": "seed",
        })

    for i, chunk in enumerate(_chunks(b["platform"]), 1):
        filters.append({
            "key": f"business.platform.{i}",
            "description": f"Machine-only platform notices ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Admin and skip the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Admin"], "removeLabelIds": ["INBOX"]},
            "source": "seed",
        })

    #  Split from `platform` on purpose: these send mail because a person did
    #  something, so they get labelled but never archived.
    for i, chunk in enumerate(_chunks(b.get("collab", [])), 1):
        filters.append({
            "key": f"business.collab.{i}",
            "description": f"Collaboration tools where a person triggered the "
                           f"mail ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Admin, stay in the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Admin"]},
            "source": "seed",
        })

    for i, chunk in enumerate(_chunks(seed_news), 1):
        filters.append({
            "key": f"business.newsletters.seed.{i}",
            "description": f"Newsletters ({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Newsletters and skip the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Newsletters"], "removeLabelIds": ["INBOX"]},
            "source": "seed",
        })

    for i, chunk in enumerate(_chunks(derived), 1):
        filters.append({
            "key": f"business.newsletters.derived.{i}",
            "description": f"Newsletters detected from your own 90-day data "
                           f"({', '.join(chunk[:3])}"
                           f"{'...' if len(chunk) > 3 else ''}) "
                           f"→ label Newsletters and skip the inbox",
            "criteria": {"from": _from_clause(chunk)},
            "action": {"addLabelNames": ["Newsletters"], "removeLabelIds": ["INBOX"]},
            "source": "derived",
            "why": {d: reasons[d] for d in chunk},
        })

    return _wrap("business", filters)


def _wrap(account: str, filters: list[dict]) -> dict:
    return {
        "account": account,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Gmail filters apply to incoming mail only. The existing "
                "backlog is handled by the cleanup phase, not by these.",
        "filters": filters,
    }


def save(spec: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2)
        fh.write("\n")


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def signature(criteria: dict, action: dict) -> str:
    """Stable identity for a filter, used to avoid creating duplicates."""
    crit = {k: str(v).strip().lower() for k, v in sorted((criteria or {}).items())}
    act = {
        "add": sorted(action.get("addLabelIds", [])),
        "remove": sorted(action.get("removeLabelIds", [])),
    }
    return json.dumps({"criteria": crit, "action": act}, sort_keys=True)


def resolve_action(client, action: dict, phase: str = "phase4") -> dict:
    """Turn addLabelNames into real label ids, creating labels as needed."""
    resolved: dict = {}
    add_ids = [client.ensure_label(n, phase=phase)
               for n in action.get("addLabelNames", [])]
    add_ids += action.get("addLabelIds", [])
    if add_ids:
        resolved["addLabelIds"] = add_ids
    if action.get("removeLabelIds"):
        resolved["removeLabelIds"] = list(action["removeLabelIds"])
    return resolved


def apply(client, spec: dict, phase: str = "phase4") -> dict:
    """Create every filter in the spec that does not already exist."""
    print(f"\n=== Phase 4: filters for {spec['account']} ===")
    try:
        existing = client.list_filters()
    except Exception as err:
        print(f"  Could not read existing filters: {err}")
        existing = []
    existing_sigs = {
        signature(f.get("criteria", {}), f.get("action", {})) for f in existing
    }

    created, skipped = [], []
    for spec_filter in spec["filters"]:
        action = resolve_action(client, spec_filter["action"], phase=phase)
        if not action:
            continue
        sig = signature(spec_filter["criteria"], action)
        if sig in existing_sigs:
            skipped.append(spec_filter["key"])
            continue
        client.create_filter(spec_filter["criteria"], action, phase=phase,
                             note=spec_filter["description"])
        existing_sigs.add(sig)
        created.append(spec_filter)
        print(f"  + {spec_filter['description']}")

    if skipped:
        print(f"  {len(skipped)} filter(s) already existed and were skipped.")
    print(f"  {len(created)} filter(s) created.")
    return {"created": created, "skipped": skipped}
