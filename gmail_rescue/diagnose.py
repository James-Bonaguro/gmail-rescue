"""Phase 1 -- read-only diagnosis.

Writes reports/diagnosis.<account>.md plus a machine-readable
reports/diagnosis.<account>.json that Phase 5 reads to produce before/after
numbers. Also caches 90 days of message metadata to
reports/metadata_cache.<account>.jsonl so the unsubscribe rankings in Phase 5
do not require a second harvest.

Nothing in this module writes to Gmail.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from .api import SUPERHUMAN_PREFIX
from .senders import aggregate, top_senders

HARVEST_HEADERS = ["From", "Subject", "List-Unsubscribe", "List-Unsubscribe-Post", "Date"]

CATEGORIES = ("primary", "promotions", "updates", "social", "forums")

#  Addresses worth probing for inbound delivery evidence. Gmail's settings API
#  can only tell us what an account forwards OUT; deliveredto: is how we get at
#  what arrives IN from somewhere else.
DELIVERED_TO_PROBES = [
    "clearbriefco@gmail.com",
    "james@intersectionstrategies.co",
    "james.bonaguro@gmail.com",
]


def cache_path(account: str, reports_dir: str = "reports") -> str:
    return os.path.join(reports_dir, f"metadata_cache.{account}.jsonl")


def check_superhuman_activity(client, since_epoch: int) -> list[dict]:
    """Has anything been labelled by Superhuman since the run started?

    OAuth revocation stops the app, but Gmail *filters* survive revocation and
    keep applying labels. A hit here means a leftover filter is still running,
    which is exactly what Phase 2 step 1 removes.
    """
    hits = []
    for name, lab in client.labels_by_name().items():
        if not name.startswith(SUPERHUMAN_PREFIX):
            continue
        ids = client.list_message_ids(
            f"after:{since_epoch}", harden=False, label_ids=[lab["id"]]
        )
        if ids:
            hits.append({"label": name, "count": len(ids), "sample": ids[:5]})
    return hits


def run(client, account: str, *, days: int = 90, max_harvest: int = 40000,
        reports_dir: str = "reports", since_epoch: int | None = None) -> dict:
    started = time.time()
    since_epoch = since_epoch or int(started)
    print(f"\n=== Phase 1: diagnosing {account} (read-only) ===")

    profile = client.get_profile()
    print(f"  {profile.get('emailAddress')}: "
          f"{profile.get('messagesTotal', 0):,} messages, "
          f"{profile.get('threadsTotal', 0):,} threads")

    # ------------------------------------------------------------ forwarding
    forwarding: dict = {}
    try:
        forwarding["auto_forwarding"] = client.get_auto_forwarding()
    except Exception as err:
        forwarding["auto_forwarding_error"] = str(err)
    try:
        forwarding["forwarding_addresses"] = client.list_forwarding_addresses()
    except Exception as err:
        forwarding["forwarding_addresses_error"] = str(err)

    # --------------------------------------------------------------- filters
    try:
        existing_filters = client.list_filters()
    except Exception as err:
        existing_filters = []
        print(f"  (could not read filters: {err})")

    # ---------------------------------------------------------------- labels
    labels = client.labels_by_name()
    superhuman_labels = {
        n: l for n, l in labels.items() if n.startswith(SUPERHUMAN_PREFIX)
    }

    # ------------------------------------------------------- superhuman gate
    superhuman_hits = check_superhuman_activity(client, since_epoch) if superhuman_labels else []

    # -------------------------------------------------------------- counting
    print("  Counting inbox by category...")
    inbox_total = len(client.list_message_ids("in:inbox", harden=False))
    inbox_unread = len(client.list_message_ids("in:inbox is:unread", harden=False))
    total_unread = len(client.list_message_ids("is:unread", harden=False))

    by_category = {}
    for cat in CATEGORIES:
        by_category[cat] = len(
            client.list_message_ids(f"in:inbox is:unread category:{cat}", harden=False)
        )

    # ----------------------------------------------------- delivered-to probe
    delivered_to = {}
    for addr in DELIVERED_TO_PROBES:
        ids = client.list_message_ids(f"deliveredto:{addr}", harden=False)
        newest = None
        if ids:
            metas = list(client.fetch_metadata(ids[:1], ["Date"], progress_every=0))
            if metas:
                newest = metas[0].get("headers", {}).get("date")
        delivered_to[addr] = {"count": len(ids), "newest": newest}

    # ---------------------------------------------------------- 90d harvest
    print(f"  Harvesting {days} days of message metadata for sender analysis...")
    harvest_ids = client.list_message_ids(f"newer_than:{days}d", harden=False)
    truncated = False
    if len(harvest_ids) > max_harvest:
        print(f"  {len(harvest_ids):,} messages in window; capping at {max_harvest:,}.")
        harvest_ids = harvest_ids[:max_harvest]
        truncated = True
    print(f"  {len(harvest_ids):,} messages to fetch "
          f"(~{max(1, len(harvest_ids) // 50):,} batched requests).")

    path = cache_path(account, reports_dir)
    metas: list[dict] = []
    with open(path, "w", encoding="utf-8") as fh:
        for meta in client.fetch_metadata(harvest_ids, HARVEST_HEADERS):
            metas.append(meta)
            fh.write(json.dumps(meta, separators=(",", ":")) + "\n")
    print(f"  Cached {len(metas):,} records to {path}")

    stats = aggregate(metas)
    top30 = top_senders(stats, 30)

    inbox_with_unsub = sum(
        1 for m in metas
        if "INBOX" in m.get("labelIds", []) and m.get("headers", {}).get("list-unsubscribe")
    )
    inbox_in_window = sum(1 for m in metas if "INBOX" in m.get("labelIds", []))

    summary = {
        "account": account,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_epoch": since_epoch,
        "profile": profile,
        "forwarding": forwarding,
        "filters": existing_filters,
        "labels": {
            n: {
                "id": l.get("id"),
                "messagesTotal": l.get("messagesTotal", 0),
                "messagesUnread": l.get("messagesUnread", 0),
                "threadsTotal": l.get("threadsTotal", 0),
                "threadsUnread": l.get("threadsUnread", 0),
            }
            for n, l in sorted(labels.items())
        },
        "superhuman_labels": sorted(superhuman_labels),
        "superhuman_active_hits": superhuman_hits,
        "counts": {
            "inbox_total": inbox_total,
            "inbox_unread": inbox_unread,
            "total_unread": total_unread,
            "unread_by_category": by_category,
            "inbox_messages_with_list_unsubscribe": inbox_with_unsub,
            "inbox_messages_in_window": inbox_in_window,
        },
        "delivered_to": delivered_to,
        "harvest": {
            "days": days,
            "messages": len(metas),
            "truncated": truncated,
            "cache": path,
        },
        "top_senders": [
            {
                "key": s.key,
                "domain": s.domain,
                "total": s.total,
                "unread": s.unread,
                "read": s.read,
                "with_unsubscribe": s.with_unsubscribe,
                "unsub_http": s.unsub_http,
                "unsub_mailto": s.unsub_mailto,
                "one_click": s.one_click,
            }
            for s in top30
        ],
        "elapsed_seconds": round(time.time() - started, 1),
    }

    json_path = os.path.join(reports_dir, f"diagnosis.{account}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    md_path = os.path.join(reports_dir, f"diagnosis.{account}.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(render(summary))
    print(f"  Wrote {md_path}")
    return summary


def render(s: dict) -> str:
    """Render the diagnosis as Markdown."""
    p = s["profile"]
    c = s["counts"]
    out: list[str] = []
    add = out.append

    add(f"# Diagnosis — {s['account']} ({p.get('emailAddress','?')})\n")
    add(f"Generated {s['generated_at']} · read-only, nothing was modified.\n")

    add("\n## Account\n")
    add(f"- Address: `{p.get('emailAddress','?')}`")
    add(f"- Total messages: {p.get('messagesTotal',0):,}")
    add(f"- Total threads: {p.get('threadsTotal',0):,}")

    add("\n## Does this account forward anywhere?\n")
    af = s["forwarding"].get("auto_forwarding") or {}
    fas = s["forwarding"].get("forwarding_addresses") or []
    if s["forwarding"].get("auto_forwarding_error"):
        add(f"- Auto-forwarding: could not read "
            f"(`{s['forwarding']['auto_forwarding_error']}`)")
    else:
        enabled = af.get("enabled", False)
        add(f"- **Auto-forwarding: {'ON' if enabled else 'OFF'}**")
        if enabled:
            add(f"  - Forwards to: `{af.get('emailAddress','?')}`")
            add(f"  - Disposition: `{af.get('disposition','?')}`")
    if fas:
        add("- Configured forwarding addresses:")
        for fa in fas:
            add(f"  - `{fa.get('forwardingEmail')}` "
                f"(status: {fa.get('verificationStatus','?')})")
    else:
        add("- Configured forwarding addresses: none")

    add("\n> These settings describe what this account forwards **out**. "
        "A rule configured on some *other* account to forward mail *in* is "
        "invisible to this API, so the delivered-to counts below are the "
        "evidence for inbound flow.\n")

    add("\n### Inbound delivery evidence\n")
    add("| Address mail was delivered to | Messages | Newest |")
    add("|---|---:|---|")
    for addr, info in s["delivered_to"].items():
        newest = info.get("newest") or "—"
        add(f"| `{addr}` | {info['count']:,} | {newest} |")

    add("\n## Existing Gmail filters\n")
    filters = s["filters"]
    if not filters:
        add("None.")
    else:
        add(f"{len(filters)} filter(s):\n")
        add("| id | criteria | adds | removes |")
        add("|---|---|---|---|")
        for f in filters:
            crit = ", ".join(f"{k}={v}" for k, v in (f.get("criteria") or {}).items())
            act = f.get("action") or {}
            add(f"| `{f.get('id','')[:16]}` | {crit or '—'} | "
                f"{', '.join(act.get('addLabelIds', [])) or '—'} | "
                f"{', '.join(act.get('removeLabelIds', [])) or '—'} |")

    add("\n## Labels\n")
    add("| Label | Threads | Unread threads | Messages | Unread messages |")
    add("|---|---:|---:|---:|---:|")
    for name, l in s["labels"].items():
        add(f"| {name} | {l['threadsTotal']:,} | {l['threadsUnread']:,} | "
            f"{l['messagesTotal']:,} | {l['messagesUnread']:,} |")

    if s["superhuman_labels"]:
        add(f"\n**{len(s['superhuman_labels'])} `[Superhuman]` label(s) present.**\n")
        hits = s["superhuman_active_hits"]
        if hits:
            add("> **WARNING — Superhuman is still labelling mail.** Messages "
                "received after this run started already carry these labels, "
                "which means a leftover Gmail filter is applying them. Labelling "
                "work will be blocked until Phase 2 removes those filters.\n")
            for h in hits:
                add(f"> - `{h['label']}`: {h['count']} new message(s)")
        else:
            add("No `[Superhuman]` label has been applied since this run "
                "started — consistent with the OAuth revocation having worked.")
    else:
        add("\nNo `[Superhuman]` labels on this account.")

    add("\n## Inbox\n")
    add(f"- Inbox messages: **{c['inbox_total']:,}**")
    add(f"- Inbox unread: **{c['inbox_unread']:,}**")
    add(f"- Total unread (including archived): **{c['total_unread']:,}**")
    add("\n### Unread in inbox, by category\n")
    add("| Category | Unread |")
    add("|---|---:|")
    for cat, n in c["unread_by_category"].items():
        add(f"| {cat} | {n:,} |")

    h = s["harvest"]
    add(f"\n- Inbox messages in the last {h['days']} days carrying a "
        f"`List-Unsubscribe` header: **{c['inbox_messages_with_list_unsubscribe']:,}** "
        f"of {c['inbox_messages_in_window']:,}")

    add(f"\n## Top 30 sender domains, last {h['days']} days\n")
    if h["truncated"]:
        add(f"> Harvest was capped at {h['messages']:,} messages; counts below "
            f"are a floor, not a total.\n")
    add("| # | Sender | Total | Read | Unread | Has unsubscribe |")
    add("|---:|---|---:|---:|---:|---|")
    for i, t in enumerate(s["top_senders"], 1):
        unsub = "yes" if t["with_unsubscribe"] else "no"
        add(f"| {i} | {t['key']} | {t['total']:,} | {t['read']:,} | "
            f"{t['unread']:,} | {unsub} |")

    add(f"\n---\nHarvest: {h['messages']:,} messages over {h['days']} days "
        f"in {s['elapsed_seconds']}s. Cache: `{h['cache']}`\n")
    return "\n".join(out) + "\n"
