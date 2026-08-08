"""Phase 5 -- the handoff report.

Reads the Phase 1 diagnosis snapshot for "before", re-counts live for "after",
and pulls the unsubscribe rankings out of the cached 90-day metadata harvest so
no second harvest is needed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .diagnose import cache_path
from .oplog import OpLog
from .senders import aggregate, top_senders

WEEKLY_WORKFLOW = """\
Once a week, open the personal account and work three places in order. Start in
the inbox: after the filters have been running, what is left there is mail with
a person behind it plus anything carrying **Finances** or **IS**, so it should
read like a short list rather than a feed. Clear it. Then open **Newsletters**
and skim — nothing in there was ever allowed to interrupt you, so read what you
want and select-all-archive the rest without guilt. Then check **01_VIP** to be
sure nothing from a real person slipped past you mid-week. The business account
is the same loop with **Clients**, **Leads** and **Admin** in place of the
personal labels: inbox first, **Admin** when you want to see what the platforms
have been telling you, **IS/Receipts 2026** at month end when you reconcile.
The whole pass should take about fifteen minutes. If it starts taking longer,
it means a new sender has slipped past the filters — add its domain to
`config/domains.json`, re-run `filters --account <name>`, and it never
interrupts you again.
"""


def _count(client, query: str) -> int:
    return len(client.list_message_ids(query, harden=False))


def collect_after(client, account: str) -> dict:
    return {
        "inbox_total": _count(client, "in:inbox"),
        "inbox_unread": _count(client, "in:inbox is:unread"),
        "total_unread": _count(client, "is:unread"),
    }


def unsubscribe_candidates(account: str, reports_dir: str = "reports",
                           limit: int = 25) -> list:
    """Top senders by 90-day volume, each with a usable unsubscribe target.

    TLDR and Product Hunt are split per edition by senders.aggregate(), because
    each edition carries a different unsubscribe link and the whole point is to
    keep the ones actually worth skimming.
    """
    path = cache_path(account, reports_dir)
    if not os.path.exists(path):
        return []
    metas = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                metas.append(json.loads(line))

    stats = aggregate(metas)
    ranked = [s for s in top_senders(stats, limit * 4) if s.with_unsubscribe > 0]
    return ranked[:limit]


def build(accounts: dict, reports_dir: str = "reports") -> str:
    """Render reports/after.md across both accounts.

    `accounts` maps account name -> {"before": dict|None, "after": dict,
    "cleanup": dict, "filters": dict, "oplog": list}
    """
    out: list[str] = []
    add = out.append

    add("# Gmail rescue — handoff report\n")
    add(f"Generated {datetime.now(timezone.utc).isoformat()}\n")
    add("\n**Nothing was deleted.** Archiving removed the `INBOX` label only; "
        "every message is still in All Mail and still searchable. Starred mail, "
        "SENT, DRAFT, SPAM and TRASH were excluded from every operation.\n")

    # ------------------------------------------------------------- headline
    add("\n## Before and after\n")
    add("| Account | Inbox unread | Total unread | Inbox messages |")
    add("|---|---|---|---|")
    for name, data in accounts.items():
        before, after = data.get("before"), data.get("after") or {}
        if before:
            bc = before["counts"]
            add(f"| **{name}** | {bc['inbox_unread']:,} → "
                f"**{after.get('inbox_unread', 0):,}** | "
                f"{bc['total_unread']:,} → **{after.get('total_unread', 0):,}** | "
                f"{bc['inbox_total']:,} → **{after.get('inbox_total', 0):,}** |")
        else:
            add(f"| **{name}** | ? → {after.get('inbox_unread', 0):,} | "
                f"? → {after.get('total_unread', 0):,} | "
                f"? → {after.get('inbox_total', 0):,} |")

    # --------------------------------------------------------------- labels
    add("\n## Labels\n")
    for name, data in accounts.items():
        cleanup = data.get("cleanup") or {}
        sh = cleanup.get("superhuman") or {}
        deleted = sh.get("labels_deleted") or []
        created = cleanup.get("labels_created") or []
        add(f"\n**{name}**\n")
        if deleted:
            add(f"- Deleted ({len(deleted)}): "
                + ", ".join(f"`{d}`" for d in deleted))
        else:
            add("- Deleted: none")
        if created:
            add(f"- Created ({len(created)}): "
                + ", ".join(f"`{c}`" for c in created))
        else:
            add("- Created: none (all required labels already existed)")
        filters_deleted = sh.get("filters_deleted") or []
        if filters_deleted:
            add(f"- Superhuman filter rules removed: {len(filters_deleted)}")
            for f in filters_deleted:
                add(f"  - `{f['id'][:16]}` applied {', '.join(f['labels'])}")

    # -------------------------------------------------------------- filters
    add("\n## Filters created\n")
    add("Gmail filters act on **incoming mail only** — they do nothing to the "
        "existing backlog, which is why the cleanup passes ran first.\n")
    for name, data in accounts.items():
        created = ((data.get("filters") or {}).get("created")) or []
        add(f"\n**{name}** — {len(created)} filter(s)\n")
        for f in created:
            tag = " *(derived from your data)*" if f.get("source") == "derived" else ""
            add(f"- {f['description']}{tag}")
        if not created:
            add("- None created (all already existed).")

    # ------------------------------------------------------------ large ops
    flagged = []
    for name, data in accounts.items():
        for rec in data.get("oplog") or []:
            if rec.get("flagged_large"):
                flagged.append((name, rec))
    if flagged:
        add("\n## Operations over 5,000 messages\n")
        add("These proceeded as instructed and are flagged here:\n")
        add("| Account | Operation | Messages | Query |")
        add("|---|---|---:|---|")
        for name, rec in flagged:
            add(f"| {name} | {rec['phase']}/{rec['action']} | {rec['count']:,} | "
                f"`{rec.get('query') or '—'}` |")

    # -------------------------------------------------------- unsubscribes
    add("\n## Top 25 unsubscribe candidates (personal, last 90 days)\n")
    add("Ranked by volume. TLDR and Product Hunt are broken out per edition so "
        "you can keep the ones you actually skim. One-click links can be opened "
        "and forgotten; the rest may need a confirmation click.\n")
    candidates = unsubscribe_candidates("personal", reports_dir, 25)
    if not candidates:
        add("_No cached 90-day harvest found — run `diagnose --account personal` "
            "first._")
    else:
        add("| # | Sender | 90d | Unread | One-click | Unsubscribe |")
        add("|---:|---|---:|---:|:---:|---|")
        for i, s in enumerate(candidates, 1):
            link = s.best_unsub or "—"
            if link.startswith("http"):
                link = f"[unsubscribe]({link})"
            elif link.startswith("mailto:"):
                link = f"`{link}`"
            add(f"| {i} | {s.key} | {s.total:,} | {s.unread:,} | "
                f"{'✓' if s.one_click else ''} | {link} |")

    bus = unsubscribe_candidates("business", reports_dir, 10)
    if bus:
        add("\n### Business account, top 10\n")
        add("| # | Sender | 90d | Unread | One-click | Unsubscribe |")
        add("|---:|---|---:|---:|:---:|---|")
        for i, s in enumerate(bus, 1):
            link = s.best_unsub or "—"
            if link.startswith("http"):
                link = f"[unsubscribe]({link})"
            elif link.startswith("mailto:"):
                link = f"`{link}`"
            add(f"| {i} | {s.key} | {s.total:,} | {s.unread:,} | "
                f"{'✓' if s.one_click else ''} | {link} |")

    # ----------------------------------------------------------- forwarding
    add("\n## Forwarding\n")
    for name, data in accounts.items():
        before = data.get("before")
        if not before:
            continue
        af = (before.get("forwarding") or {}).get("auto_forwarding") or {}
        fas = (before.get("forwarding") or {}).get("forwarding_addresses") or []
        state = "ON → " + af.get("emailAddress", "?") if af.get("enabled") else "OFF"
        add(f"- **{name}**: auto-forwarding {state}; "
            f"{len(fas)} configured forwarding address(es).")
        dt = before.get("delivered_to") or {}
        for addr, info in dt.items():
            if info.get("count"):
                add(f"  - Mail delivered to `{addr}`: {info['count']:,} "
                    f"(newest: {info.get('newest') or '—'})")

    add("\n> **`clearbriefco@gmail.com` still exists.** It has a rule forwarding "
        "mail into the personal account. That rule lives on *that* account, so "
        "nothing here could see or change it — the delivered-to counts above are "
        "the only evidence of it. It has been dormant since late July. If you "
        "want it off, you have to sign into clearbriefco@gmail.com and turn it "
        "off there.\n")

    # ------------------------------------------------------------- workflow
    add("\n## Your weekly workflow now\n")
    add(WEEKLY_WORKFLOW)

    # ----------------------------------------------------------------- misc
    add("\n## Judgement calls worth reviewing\n")
    add("- **`uber.com` is filtered as promotional and skips the inbox.** It was "
        "on your noise list, but Uber also sends ride receipts down the same "
        "domain. If you want those in the inbox, move `uber.com` out of "
        "`promotional` in `config/domains.json` and re-run the filters command.\n")
    add("- Filters marked *derived* were inferred from your own 90-day data: a "
        "domain qualified only if it sent 5+ messages, carried a "
        "`List-Unsubscribe` header on 80%+ of them, and you have never emailed "
        "it. Each one lists its reasoning in `config/filters.*.json`.\n")

    add("\n## Full audit trail\n")
    for name, data in accounts.items():
        n = len(data.get("oplog") or [])
        add(f"- `reports/oplog.{name}.jsonl` — {n} logged operation(s), each with "
            f"the query, the count and every message id touched. "
            f"`python -m gmail_rescue undo --account {name} --op <id>` reverses one.")

    return "\n".join(out) + "\n"


def write(accounts: dict, reports_dir: str = "reports") -> str:
    path = os.path.join(reports_dir, "after.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build(accounts, reports_dir))
    return path


def load_before(account: str, reports_dir: str = "reports") -> dict | None:
    path = os.path.join(reports_dir, f"diagnosis.{account}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_oplog(account: str, reports_dir: str = "reports") -> list[dict]:
    return OpLog.read(os.path.join(reports_dir, f"oplog.{account}.jsonl"))
