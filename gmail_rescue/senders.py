"""Parsing and aggregation of sender metadata.

Pure functions over header dicts -- no API calls -- so all of this is unit
tested offline without credentials.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from email.utils import getaddresses, parseaddr

#  Newsletters that ship many distinct editions from one domain. Each edition
#  carries its own unsubscribe link, so lumping them together would produce an
#  unsubscribe list that silently kills editions the user wants to keep.
DEFAULT_SPLIT_BY_EDITION = (
    "tldrnewsletter.com",
    "producthunt.com",
    "deeperlearning.producthunt.com",
)

_SUBJECT_SPLIT = re.compile(r"\s*[—–|:]\s*")
_WS = re.compile(r"\s+")


def extract_address(from_header: str) -> str:
    """'TLDR AI <ai@tldrnewsletter.com>' -> 'ai@tldrnewsletter.com'."""
    if not from_header:
        return ""
    _, addr = parseaddr(from_header)
    return addr.strip().lower()


def extract_display_name(from_header: str) -> str:
    """'TLDR AI <ai@tldrnewsletter.com>' -> 'TLDR AI'."""
    if not from_header:
        return ""
    name, _ = parseaddr(from_header)
    return _WS.sub(" ", name).strip().strip('"')


def extract_domain(from_header: str) -> str:
    """Sending domain, lowercased. Full subdomain is preserved deliberately:
    'e.lifetime.life' and 'lifetime.life' are different senders with different
    unsubscribe links, and the user thinks in full sending domains.
    """
    addr = extract_address(from_header)
    if "@" not in addr:
        return ""
    return addr.rsplit("@", 1)[1].strip().lower().rstrip(".")


def parse_list_unsubscribe(header: str) -> dict[str, str | None]:
    """Pull the http(s) and mailto targets out of a List-Unsubscribe header.

    The header is a comma-separated list of angle-bracketed URIs, e.g.
    '<mailto:u@x.com>, <https://x.com/u?id=1>'. Real-world headers are often
    malformed, so we fall back to a permissive scan rather than failing.
    """
    out: dict[str, str | None] = {"http": None, "mailto": None}
    if not header:
        return out

    targets = re.findall(r"<([^>]+)>", header)
    if not targets:
        targets = [p.strip() for p in header.split(",") if p.strip()]

    for raw in targets:
        uri = raw.strip().strip("<>").strip()
        low = uri.lower()
        if low.startswith(("http://", "https://")) and not out["http"]:
            out["http"] = uri
        elif low.startswith("mailto:") and not out["mailto"]:
            out["mailto"] = uri
    return out


def is_one_click(list_unsubscribe_post: str | None) -> bool:
    """True when the sender supports RFC 8058 one-click unsubscribe."""
    if not list_unsubscribe_post:
        return False
    return "one-click" in list_unsubscribe_post.lower()


def edition_key(from_header: str, subject: str, domain: str) -> str:
    """Stable per-edition name for multi-edition newsletter domains.

    Prefers the From display name ('TLDR AI'), because that is what actually
    differs per edition. Falls back to the leading segment of the subject.
    """
    name = extract_display_name(from_header)
    if name and not _looks_like_address(name):
        return name
    if subject:
        head = _SUBJECT_SPLIT.split(subject.strip(), 1)[0].strip()
        if head:
            return head[:60]
    return domain


def _looks_like_address(value: str) -> bool:
    return "@" in value


def recipients_of(headers: dict[str, str]) -> list[str]:
    """Every address in To/Cc/Bcc, lowercased."""
    raw = [headers.get(f, "") for f in ("to", "cc", "bcc")]
    pairs = getaddresses([r for r in raw if r])
    return [addr.strip().lower() for _, addr in pairs if addr and "@" in addr]


@dataclass
class SenderStats:
    key: str
    domain: str
    total: int = 0
    unread: int = 0
    with_unsubscribe: int = 0
    sample_from: str = ""
    sample_subject: str = ""
    unsub_http: str | None = None
    unsub_mailto: str | None = None
    one_click: bool = False
    addresses: set[str] = field(default_factory=set)

    @property
    def read(self) -> int:
        return self.total - self.unread

    @property
    def unsubscribe_ratio(self) -> float:
        return self.with_unsubscribe / self.total if self.total else 0.0

    @property
    def best_unsub(self) -> str:
        return self.unsub_http or self.unsub_mailto or ""


def aggregate(
    messages, split_by_edition=DEFAULT_SPLIT_BY_EDITION
) -> dict[str, SenderStats]:
    """Group message metadata by sending domain, splitting known multi-edition
    domains into one bucket per edition."""
    split = {d.lower() for d in split_by_edition}
    stats: dict[str, SenderStats] = {}

    for msg in messages:
        headers = msg.get("headers", {})
        from_header = headers.get("from", "")
        domain = extract_domain(from_header)
        if not domain:
            continue

        subject = headers.get("subject", "")
        if domain in split:
            key = f"{domain} :: {edition_key(from_header, subject, domain)}"
        else:
            key = domain

        entry = stats.get(key)
        if entry is None:
            entry = stats[key] = SenderStats(key=key, domain=domain)

        entry.total += 1
        if "UNREAD" in msg.get("labelIds", []):
            entry.unread += 1
        addr = extract_address(from_header)
        if addr:
            entry.addresses.add(addr)

        unsub_header = headers.get("list-unsubscribe", "")
        if unsub_header:
            entry.with_unsubscribe += 1
            if not entry.best_unsub:
                parsed = parse_list_unsubscribe(unsub_header)
                entry.unsub_http = parsed["http"]
                entry.unsub_mailto = parsed["mailto"]
                entry.one_click = is_one_click(
                    headers.get("list-unsubscribe-post")
                )
                entry.sample_from = from_header
                entry.sample_subject = subject
        if not entry.sample_from:
            entry.sample_from = from_header
            entry.sample_subject = subject

    return stats


def top_senders(stats: dict[str, SenderStats], limit: int = 30) -> list[SenderStats]:
    return sorted(stats.values(), key=lambda s: (-s.total, s.key))[:limit]


def domain_totals(stats: dict[str, SenderStats]) -> dict[str, SenderStats]:
    """Collapse edition splits back to one entry per domain."""
    merged: dict[str, SenderStats] = {}
    for entry in stats.values():
        agg = merged.get(entry.domain)
        if agg is None:
            agg = merged[entry.domain] = SenderStats(
                key=entry.domain, domain=entry.domain
            )
        agg.total += entry.total
        agg.unread += entry.unread
        agg.with_unsubscribe += entry.with_unsubscribe
        agg.addresses |= entry.addresses
        if not agg.best_unsub and entry.best_unsub:
            agg.unsub_http = entry.unsub_http
            agg.unsub_mailto = entry.unsub_mailto
            agg.one_click = entry.one_click
    return merged


def derive_newsletter_domains(
    stats: dict[str, SenderStats],
    correspondents: set[str],
    excluded_domains: set[str],
    *,
    min_messages: int = 5,
    min_unsubscribe_ratio: float = 0.8,
) -> list[tuple[str, str]]:
    """Find domains that are obviously newsletters, from the data.

    A domain qualifies when it sends at regular volume, nearly always carries a
    List-Unsubscribe header, has never been emailed by the user, and is not
    already classified as a bank, receipt or platform sender.

    Returns (domain, human-readable reason) so the report can show its work.
    """
    found: list[tuple[str, str]] = []
    for domain, entry in sorted(domain_totals(stats).items()):
        if domain in excluded_domains:
            continue
        if entry.total < min_messages:
            continue
        if entry.unsubscribe_ratio < min_unsubscribe_ratio:
            continue
        if entry.addresses & correspondents:
            continue
        found.append((
            domain,
            f"{entry.total} msgs/90d, "
            f"{entry.unsubscribe_ratio:.0%} carry List-Unsubscribe, "
            f"never emailed by you",
        ))
    return found
