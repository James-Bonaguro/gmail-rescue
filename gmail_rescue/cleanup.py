"""Phase 2 (personal) and Phase 3 (business) cleanup.

Both accounts share the same archive and badge-kill machinery; they differ in
which labels exist and which buckets get applied. Nothing here deletes mail --
"archive" means removing the INBOX label and nothing else, and every message
stays in All Mail, fully searchable.
"""

from __future__ import annotations

import json
import os

from .api import SUPERHUMAN_PREFIX, SafetyViolation
from .guards import GuardSet, build_correspondent_set, resolve_protected_labels
from .senders import extract_domain

#  Labels guarded against the two broad sweeps, per account.
PROTECTED_LABEL_NAMES = {
    "personal": ["01_VIP"],
    "business": [],
}

#  Labels the brief says to preserve and reuse. Created if missing so that
#  filters referencing them always resolve.
PRESERVE_LABELS = {
    "personal": [
        "01_VIP", "Newsletters", "Finances", "Shopping",
        "Health / Fitness", "Personal/Entertainment", "IS", "IS/Receipts 2026",
    ],
    "business": [
        "Clients", "Leads", "Admin", "Newsletters", "IS", "IS/Receipts 2026",
    ],
}

DOMAIN_QUERY_CHUNK = 20


def load_config(path: str = "config/domains.json") -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def domain_or_query(domains: list[str]) -> list[str]:
    """Build `from:` OR-clauses, chunked so no single query gets unwieldy."""
    out = []
    for i in range(0, len(domains), DOMAIN_QUERY_CHUNK):
        chunk = domains[i : i + DOMAIN_QUERY_CHUNK]
        out.append("(" + " OR ".join(f"from:{d}" for d in chunk) + ")")
    return out


# --------------------------------------------------------------- superhuman


def kill_superhuman(client) -> dict:
    """Remove the Superhuman filters first, then its labels.

    Order matters. Filters survive an OAuth revocation and keep applying
    labels, so deleting the labels first would leave live filters pointing at
    nothing -- and would destroy the evidence of which filters were guilty.
    Deleting a label never deletes messages.
    """
    print("\n--- Superhuman teardown ---")
    labels = client.labels_by_name()
    sh_labels = {n: l for n, l in labels.items() if n.startswith(SUPERHUMAN_PREFIX)}
    if not sh_labels:
        print("  No [Superhuman] labels on this account. Nothing to do.")
        return {"filters_deleted": [], "labels_deleted": []}

    id_to_name = {l["id"]: n for n, l in labels.items()}
    sh_ids = {l["id"] for l in sh_labels.values()}

    filters_deleted = []
    try:
        for f in client.list_filters():
            action = f.get("action") or {}
            touched = set(action.get("addLabelIds", [])) | set(
                action.get("removeLabelIds", [])
            )
            hit = touched & sh_ids
            if hit:
                names = sorted(id_to_name.get(i, i) for i in hit)
                client.remove_filter(f["id"], note=f"applied {', '.join(names)}")
                filters_deleted.append({"id": f["id"], "labels": names})
        print(f"  Deleted {len(filters_deleted)} Superhuman filter(s).")
    except Exception as err:
        print(f"  Could not enumerate filters: {err}")

    labels_deleted = []
    for name in sorted(sh_labels):
        if client.delete_superhuman_label(name):
            labels_deleted.append(name)
    print(f"  Deleted {len(labels_deleted)} [Superhuman] label(s). "
          f"No messages were removed.")
    return {"filters_deleted": filters_deleted, "labels_deleted": labels_deleted}


# ------------------------------------------------------------------ passes


def unguarded_archive_passes(client, phase: str) -> dict:
    """Bulk machine mail. No guards needed -- promotions, updates and social
    are Gmail's own classification of non-personal mail."""
    print("\n--- Archive passes (categories) ---")
    results = {}
    for name, query in (
        ("promotions", "in:inbox category:promotions older_than:2d"),
        ("updates", "in:inbox category:updates older_than:2d"),
        ("social", "in:inbox category:social"),
    ):
        ids = client.list_message_ids(query)
        res = client.archive(ids, phase=phase, action=f"archive_{name}",
                             query=query, mark_read=True)
        results[name] = res.count
    return results


def guarded_sweeps(client, phase: str, guards: GuardSet) -> dict:
    """The two broad sweeps, behind the human-mail guards.

    Both draw from one candidate pool -- everything in the inbox older than 30
    days -- because they partition it: unread goes one way, read the other.
    Harvesting once halves the API cost.
    """
    print("\n--- Guarded sweeps (stale unread + read backlog) ---")
    query = "in:inbox older_than:30d"
    candidate_ids = client.list_message_ids(query)
    print(f"  {len(candidate_ids):,} candidate messages older than 30 days.")
    if not candidate_ids:
        return {"stale_unread": 0, "read_sweep": 0, "protected": 0}

    print("  Fetching metadata to apply guards...")
    metas = list(client.fetch_metadata(candidate_ids, ["From"]))
    actionable, protected = guards.partition(metas)
    print(f"  {len(protected):,} protected (VIP or someone you have emailed).")
    print(f"  {len(actionable):,} actionable.")

    stale_unread = [m["id"] for m in actionable if "UNREAD" in m.get("labelIds", [])]
    read_backlog = [m["id"] for m in actionable if "UNREAD" not in m.get("labelIds", [])]

    r1 = client.archive(stale_unread, phase=phase, action="archive_stale_unread",
                        query=f"{query} is:unread [guarded]", mark_read=True)
    r2 = client.archive(read_backlog, phase=phase, action="archive_read_backlog",
                        query=f"{query} is:read [guarded]", mark_read=False)

    client.oplog.record(phase, "guard_skipped", query=query,
                        count=len(protected), dry_run=client.dry_run,
                        note="VIP label or known correspondent")
    return {
        "stale_unread": r1.count,
        "read_sweep": r2.count,
        "protected": len(protected),
    }


def badge_kill(client, phase: str) -> int:
    """Clear phantom unread on already-archived mail.

    Removes UNREAD only. Nothing moves; the badge count drops.
    """
    print("\n--- Badge kill (archived unread) ---")
    query = "is:unread -in:inbox older_than:30d"
    ids = client.list_message_ids(query)
    res = client.batch_modify(ids, remove_label_ids=["UNREAD"], phase=phase,
                              action="badge_kill", query=query)
    return res.count


def label_domains_in_inbox(client, domains: list[str], label_name: str, *,
                           phase: str, action: str, archive: bool = False) -> int:
    """Apply a label to inbox mail from a set of domains.

    Used for the bank/card mail on personal (stays in the inbox) and the
    receipt/platform buckets on business.
    """
    if not domains:
        return 0
    label_id = client.ensure_label(label_name, phase=phase)
    total = 0
    for clause in domain_or_query(domains):
        query = f"in:inbox {clause}"
        ids = client.list_message_ids(query)
        res = client.batch_modify(
            ids,
            add_label_ids=[label_id],
            remove_label_ids=["INBOX"] if archive else None,
            phase=phase, action=action, query=query,
            note=f"label={label_name}",
        )
        total += res.count
    return total


# ------------------------------------------------------------------- phases


def run_personal(client, config: dict, *, reports_dir: str = "reports") -> dict:
    phase = "phase2"
    print("\n=== Phase 2: personal account cleanup ===")
    summary: dict = {}

    summary["superhuman"] = kill_superhuman(client)

    for name in PRESERVE_LABELS["personal"]:
        client.ensure_label(name, phase=phase)

    correspondents = build_correspondent_set(
        client, cache_path=os.path.join(reports_dir, "correspondents.personal.json")
    )
    protected_ids = resolve_protected_labels(
        client, PROTECTED_LABEL_NAMES["personal"]
    )
    guards = GuardSet(correspondents=correspondents, protected_label_ids=protected_ids)

    summary["archive"] = unguarded_archive_passes(client, phase)
    summary["sweeps"] = guarded_sweeps(client, phase, guards)
    summary["badge_kill"] = badge_kill(client, phase)

    print("\n--- Auto-label finance mail (stays in inbox) ---")
    summary["finances"] = label_domains_in_inbox(
        client, config["personal"]["banks"], "Finances",
        phase=phase, action="label_finances", archive=False,
    )

    summary["correspondents"] = len(correspondents)
    return summary


def run_business(client, config: dict, *, reports_dir: str = "reports") -> dict:
    phase = "phase3"
    print("\n=== Phase 3: business account rebuild ===")
    summary: dict = {}

    print("\n--- Creating label structure ---")
    created = []
    existing = set(client.labels_by_name())
    for name in PRESERVE_LABELS["business"]:
        if name not in existing:
            created.append(name)
        client.ensure_label(name, phase=phase)
    summary["labels_created"] = created
    print(f"  {len(created)} label(s) created: {', '.join(created) or 'none'}")

    #  Superhuman never ran here, but check rather than assume.
    summary["superhuman"] = kill_superhuman(client)

    correspondents = build_correspondent_set(
        client, cache_path=os.path.join(reports_dir, "correspondents.business.json")
    )
    guards = GuardSet(correspondents=correspondents, protected_label_ids=set())

    summary["archive"] = unguarded_archive_passes(client, phase)
    summary["sweeps"] = guarded_sweeps(client, phase, guards)
    summary["badge_kill"] = badge_kill(client, phase)

    print("\n--- Bucketing from this account's own sender data ---")
    buckets, notes = classify_business_domains(
        config, correspondents, reports_dir=reports_dir
    )
    summary["receipts"] = label_domains_in_inbox(
        client, buckets["receipts"], "IS/Receipts 2026",
        phase=phase, action="label_receipts", archive=False,
    )
    summary["admin"] = label_domains_in_inbox(
        client, buckets["platform"] + buckets["collab"], "Admin",
        phase=phase, action="label_admin", archive=False,
    )
    summary["buckets"] = buckets
    summary["correspondents"] = len(correspondents)

    path = os.path.join(reports_dir, "business_classification.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(notes)
    print(f"  Wrote {path}")
    return summary


def classify_business_domains(config: dict, correspondents: set[str], *,
                              reports_dir: str = "reports") -> tuple[dict, str]:
    """Bucket business senders using that account's own harvested data.

    Only domains that match a configured list are ever acted on. An unmatched
    domain is left completely alone -- that is how "anything from an actual
    human stays untouched in the inbox" is enforced without asking anyone to
    classify a sender.
    """
    from .diagnose import cache_path
    from .senders import aggregate, domain_totals

    cache = cache_path("business", reports_dir)
    observed: dict = {}
    if os.path.exists(cache):
        metas = []
        with open(cache, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    metas.append(json.loads(line))
        observed = domain_totals(aggregate(metas))

    cfg = config["business"]
    never = set(config.get("never_auto_classify", []))

    buckets = {"receipts": [], "platform": [], "collab": [], "newsletters": []}
    lines = ["# Business sender classification\n",
             "Only domains matching a configured list are acted on. Everything "
             "else is left in the inbox untouched.\n",
             "\n| Domain | 90d messages | Bucket | Why |",
             "|---|---:|---|---|"]

    for bucket, key in (("receipts", "receipts"), ("platform", "platform"),
                        ("collab", "collab"), ("newsletters", "newsletters")):
        for domain in cfg.get(key, []):
            if domain in never:
                continue
            buckets[bucket].append(domain)
            seen = observed.get(domain)
            count = seen.total if seen else 0
            lines.append(f"| {domain} | {count:,} | {bucket} | configured seed |")

    untouched = sorted(
        (d, s.total) for d, s in observed.items()
        if d not in set(sum(buckets.values(), [])) and s.total >= 3
    )
    if untouched:
        lines.append("\n## Left untouched (unmatched senders)\n")
        lines.append("| Domain | 90d messages |")
        lines.append("|---|---:|")
        for domain, count in sorted(untouched, key=lambda x: -x[1])[:40]:
            lines.append(f"| {domain} | {count:,} |")

    return buckets, "\n".join(lines) + "\n"


# ---------------------------------------------------------------- preflight


def preflight(client, account: str) -> dict:
    """Count everything the cleanup would touch, without touching anything.

    This is the real go/no-go check: run it, read the numbers, then run the
    cleanup for real.
    """
    print(f"\n=== Preflight for {account} (nothing will be modified) ===")
    profile = client.get_profile()
    print(f"  {profile.get('emailAddress')}")

    labels = client.labels_by_name()
    sh = [n for n in labels if n.startswith(SUPERHUMAN_PREFIX)]
    print(f"  [Superhuman] labels present: {len(sh)}")
    for name in sh:
        print(f"    - {name}")

    counts = {}
    for name, query in (
        ("promotions >2d", "in:inbox category:promotions older_than:2d"),
        ("updates >2d", "in:inbox category:updates older_than:2d"),
        ("social", "in:inbox category:social"),
        ("inbox >30d (sweep pool)", "in:inbox older_than:30d"),
        ("archived unread >30d", "is:unread -in:inbox older_than:30d"),
    ):
        n = len(client.list_message_ids(query))
        counts[name] = n
        flag = "  << over 5,000" if n > 5000 else ""
        print(f"  {name:<28} {n:>8,}{flag}")

    print("\n  Guards are applied after metadata fetch, so the sweep pool "
          "above is an upper bound, not the number that will move.")
    return {"profile": profile, "superhuman_labels": sh, "counts": counts}
