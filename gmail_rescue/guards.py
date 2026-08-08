"""Protection for mail that has a person behind it.

The brief's rule of thumb is "mail with a person behind it stays in the inbox
untouched; machine mail gets a label". The stale long-tail and read-mail sweeps
are the two passes broad enough to catch real correspondence, so they run
behind these guards.

Both guards are derived from the account's own data. Neither asks the user to
classify anything:

  * correspondents -- anyone the user has addressed in SENT mail. If you have
    emailed them, their reply is not machine mail.
  * VIP -- anything carrying the 01_VIP label on the personal account.

Guards are applied locally against harvested metadata rather than bolted onto
the Gmail query, because label names containing spaces, slashes or brackets are
a persistent source of quoting bugs in Gmail search syntax.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .senders import extract_address, recipients_of


@dataclass
class GuardSet:
    correspondents: set[str]
    protected_label_ids: set[str]

    def is_protected(self, meta: dict) -> tuple[bool, str]:
        """Return (protected, reason) for one message's metadata."""
        label_ids = set(meta.get("labelIds", []))
        overlap = label_ids & self.protected_label_ids
        if overlap:
            return True, "protected label"
        sender = extract_address(meta.get("headers", {}).get("from", ""))
        if sender and sender in self.correspondents:
            return True, "you have emailed this sender"
        return False, ""

    def partition(self, metas: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split metadata into (actionable, protected)."""
        actionable, protected = [], []
        for meta in metas:
            is_prot, _ = self.is_protected(meta)
            (protected if is_prot else actionable).append(meta)
        return actionable, protected


def build_correspondent_set(client, months: int = 12,
                            cache_path: str | None = None) -> set[str]:
    """Every address the user has written to, from their own SENT mail.

    This is the data-derived definition of "a real person". Deliberately
    address-level, never domain-level: treating the whole of gmail.com as
    protected because you once emailed a friend would defeat the cleanup.

    Cached to disk because Phase 4's newsletter detection needs the same set,
    and re-harvesting SENT is the most wasteful thing this tool could do.
    """
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            cached = set(json.load(fh))
        print(f"  Reusing {len(cached):,} known correspondents from {cache_path}")
        return cached

    print(f"  Building correspondent set from SENT mail (last {months} months)...")
    #  harden=False: this query is read-only and deliberately targets SENT,
    #  which the mutation hardening excludes by design.
    sent_ids = client.list_message_ids(
        f"in:sent newer_than:{months}m", harden=False
    )
    print(f"  {len(sent_ids):,} sent messages to scan.")

    correspondents: set[str] = set()
    for meta in client.fetch_metadata(sent_ids, ["To", "Cc", "Bcc"]):
        correspondents.update(recipients_of(meta.get("headers", {})))

    #  Mailing lists and no-reply addresses are not people. Dropping them keeps
    #  a single "unsubscribe" reply from permanently protecting a newsletter.
    filtered = {
        addr for addr in correspondents
        if not any(
            token in addr
            for token in ("no-reply", "noreply", "donotreply", "do-not-reply",
                          "unsubscribe", "mailer-daemon", "postmaster")
        )
    }
    print(f"  {len(filtered):,} distinct people you have emailed.")
    if cache_path:
        os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(sorted(filtered), fh)
    return filtered


def resolve_protected_labels(client, names: list[str]) -> set[str]:
    """Map protected label names to ids, skipping any that do not exist."""
    by_name = client.labels_by_name()
    out = set()
    for name in names:
        lab = by_name.get(name)
        if lab:
            out.add(lab["id"])
        else:
            print(f"  (no '{name}' label on this account -- guard not applicable)")
    return out
