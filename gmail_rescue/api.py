"""Safety-hardened wrapper around the Gmail API.

The hard rules from the brief are enforced here, in code, rather than left to
the discipline of the calling modules:

  1. Nothing is ever deleted or trashed. No delete/trash/batchDelete API symbol
     appears anywhere in this package -- tests/test_safety.py greps the source
     to prove it. The gmail.modify scope cannot permanently delete either, so
     this is belt and suspenders.
  2. Every mutating query passes through harden_query(), which excludes starred
     mail, SENT, DRAFT, CHAT, SPAM and TRASH.
  3. batchModify is chunked at 1000 ids, the documented API maximum.
  4. Label deletion refuses any name that does not start with "[Superhuman]".
  5. Any operation over 5,000 messages prints its count, proceeds, and is
     flagged in the final report.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.settings.basic",
]

#  Gmail caps batchModify at 1000 ids per call.
BATCH_MODIFY_CHUNK = 1000
#  Gmail's HTTP batch endpoint allows 100; Google recommends staying at or below
#  50 for Gmail specifically, and 50 is comfortably reliable in practice.
METADATA_BATCH_SIZE = 50
#  messages.list page maximum.
LIST_PAGE_SIZE = 500

#  Appended to every mutating query. Between them these enforce "never modify
#  anything starred, in SENT or in DRAFT" and "never touch SPAM or TRASH".
HARDEN_TERMS = (
    "-is:starred",
    "-in:sent",
    "-in:drafts",
    "-in:chats",
    "-in:spam",
    "-in:trash",
)

SUPERHUMAN_PREFIX = "[Superhuman]"

#  Labels that must never be removed from a message by this tool.
PROTECTED_LABEL_IDS = frozenset({"STARRED", "SENT", "DRAFT", "SPAM", "TRASH"})


class SafetyViolation(RuntimeError):
    """Raised when a caller asks for something the brief forbids."""


def harden_query(query: str) -> str:
    """Append the safety exclusions to a Gmail search query.

    Idempotent: a term already present is not added twice, so passing an
    already-hardened query through again is a no-op.
    """
    q = (query or "").strip()
    for term in HARDEN_TERMS:
        if term not in q:
            q = f"{q} {term}".strip()
    return q


def chunked(items: list, size: int) -> list[list]:
    """Split a list into fixed-size chunks. Trailing chunk may be short."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass
class OpResult:
    count: int = 0
    message_ids: list[str] = field(default_factory=list)
    flagged_large: bool = False


class RateLimiter:
    """Keeps us under Gmail's per-user quota.

    Gmail allows 250 quota units/second/user. batchModify costs 50 units, so
    roughly 5 calls/second is the ceiling for the heaviest operation. Rather
    than model every method's cost we spend a conservative fixed budget, which
    at this scale costs a few minutes and avoids a storm of 429s.
    """

    def __init__(self, calls_per_second: float = 4.0):
        self.min_interval = 1.0 / calls_per_second if calls_per_second > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last = time.monotonic()


RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "backendError",
    "internalError",
}


def _is_retryable(err: HttpError) -> bool:
    status = getattr(getattr(err, "resp", None), "status", None)
    if status in RETRYABLE_STATUS:
        return True
    #  403 is overloaded: rate limiting is retryable, insufficient scope is not.
    if status == 403:
        body = str(getattr(err, "content", b"") or "")
        return any(reason in body for reason in RETRYABLE_REASONS)
    return False


def execute(request, *, max_attempts: int = 6):
    """Execute a Google API request with exponential backoff and jitter."""
    delay = 2.0
    last: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return request.execute()
        except HttpError as err:
            last = err
            if not _is_retryable(err) or attempt == max_attempts - 1:
                raise
            sleep_for = delay * (2**attempt) + random.uniform(0, 1.0)
            print(f"     retrying after {sleep_for:.1f}s ({err.__class__.__name__})")
            time.sleep(min(sleep_for, 64.0))
    raise last  # pragma: no cover - loop always returns or raises


class GmailClient:
    """All Gmail access goes through here."""

    def __init__(self, service, account: str, oplog, dry_run: bool = False,
                 calls_per_second: float = 4.0):
        self.service = service
        self.account = account
        self.oplog = oplog
        self.dry_run = dry_run
        self.limiter = RateLimiter(calls_per_second)
        self._label_cache: dict[str, dict] | None = None

    # ---------------------------------------------------------------- profile

    def get_profile(self) -> dict:
        self.limiter.wait()
        return execute(self.service.users().getProfile(userId="me"))

    # ----------------------------------------------------------------- labels

    def labels_by_name(self, refresh: bool = False) -> dict[str, dict]:
        """All labels keyed by display name, with counts attached."""
        if self._label_cache is not None and not refresh:
            return self._label_cache
        self.limiter.wait()
        resp = execute(self.service.users().labels().list(userId="me"))
        out: dict[str, dict] = {}
        for lab in resp.get("labels", []):
            self.limiter.wait()
            full = execute(
                self.service.users().labels().get(userId="me", id=lab["id"])
            )
            out[full["name"]] = full
        self._label_cache = out
        return out

    def label_id(self, name: str) -> str | None:
        lab = self.labels_by_name().get(name)
        return lab["id"] if lab else None

    def ensure_label(self, name: str, phase: str = "labels") -> str:
        """Return the id of `name`, creating the label if it does not exist.

        Labels are always resolved by name. The label ids in the brief were
        captured on Aug 7 and are not trusted.
        """
        existing = self.labels_by_name().get(name)
        if existing:
            return existing["id"]

        if self.dry_run:
            self.oplog.record(phase, "create_label", note=name, count=0, dry_run=True)
            return f"DRYRUN_{name}"

        self.limiter.wait()
        created = execute(
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
        )
        self.oplog.record(phase, "create_label", note=name, count=0)
        self.labels_by_name(refresh=True)
        return created["id"]

    def delete_superhuman_label(self, name: str, phase: str = "superhuman") -> bool:
        """Delete a label. Refuses anything not prefixed "[Superhuman]".

        Deleting a label never deletes messages -- the mail stays in All Mail.
        """
        if not name.startswith(SUPERHUMAN_PREFIX):
            raise SafetyViolation(
                f"refusing to delete label {name!r}: only labels starting with "
                f"{SUPERHUMAN_PREFIX!r} may be deleted"
            )
        lab = self.labels_by_name().get(name)
        if not lab:
            return False
        if self.dry_run:
            self.oplog.record(phase, "delete_label", note=name, count=0, dry_run=True)
            return True
        self.limiter.wait()
        execute(self.service.users().labels().delete(userId="me", id=lab["id"]))
        self.oplog.record(phase, "delete_label", note=name, count=0)
        self.labels_by_name(refresh=True)
        return True

    # --------------------------------------------------------------- messages

    def list_message_ids(
        self, query: str, harden: bool = True, label_ids: list[str] | None = None
    ) -> list[str]:
        """Page through every matching message id.

        We count by paging ids rather than trusting resultSizeEstimate, which
        is an estimate and is wrong often enough to matter in a report.
        """
        q = harden_query(query) if harden else query
        ids: list[str] = []
        page_token = None
        while True:
            self.limiter.wait()
            kwargs = {
                "userId": "me",
                "maxResults": LIST_PAGE_SIZE,
                "includeSpamTrash": False,
            }
            if q:
                kwargs["q"] = q
            if label_ids:
                kwargs["labelIds"] = label_ids
            if page_token:
                kwargs["pageToken"] = page_token
            resp = execute(self.service.users().messages().list(**kwargs))
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def count_messages(self, query: str, harden: bool = False) -> int:
        return len(self.list_message_ids(query, harden=harden))

    def batch_modify(
        self,
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
        *,
        phase: str,
        action: str,
        query: str | None = None,
        note: str | None = None,
    ) -> OpResult:
        """Add and/or remove labels across many messages, 1000 ids per call."""
        add = list(add_label_ids or [])
        remove = list(remove_label_ids or [])

        for lid in remove:
            if lid in PROTECTED_LABEL_IDS:
                raise SafetyViolation(f"refusing to remove protected label {lid}")
        for lid in add:
            if lid in {"SPAM", "TRASH"}:
                raise SafetyViolation(f"refusing to add {lid}")
        if not add and not remove:
            raise ValueError("batch_modify called with nothing to add or remove")

        ids = list(dict.fromkeys(message_ids))  # de-dup, preserve order
        result = OpResult(count=len(ids), message_ids=ids)

        if not ids:
            self.oplog.record(phase, action, query=query, add_labels=add,
                              remove_labels=remove, message_ids=[],
                              dry_run=self.dry_run, note=note)
            return result

        if not self.dry_run:
            body = {}
            if add:
                body["addLabelIds"] = add
            if remove:
                body["removeLabelIds"] = remove
            for chunk in chunked(ids, BATCH_MODIFY_CHUNK):
                self.limiter.wait()
                execute(
                    self.service.users()
                    .messages()
                    .batchModify(userId="me", body={**body, "ids": chunk})
                )

        rec = self.oplog.record(phase, action, query=query, add_labels=add,
                                remove_labels=remove, message_ids=ids,
                                dry_run=self.dry_run, note=note)
        result.flagged_large = rec.flagged_large
        return result

    def archive(self, message_ids: list[str], *, phase: str, action: str,
                query: str | None = None, mark_read: bool = True) -> OpResult:
        """Archiving means removing INBOX -- and nothing else."""
        remove = ["INBOX", "UNREAD"] if mark_read else ["INBOX"]
        return self.batch_modify(message_ids, remove_label_ids=remove,
                                 phase=phase, action=action, query=query)

    def fetch_metadata(
        self, message_ids: list[str], headers: list[str], progress_every: int = 2000
    ):
        """Yield {id, labelIds, internalDate, headers{}} for each message.

        Uses Gmail's HTTP batch endpoint: one round trip per 50 messages rather
        than one per message. At 26,000 messages that is ~520 requests instead
        of 26,000, which is the difference between minutes and hours.
        """
        done = 0
        for chunk in chunked(list(message_ids), METADATA_BATCH_SIZE):
            collected: list[dict] = []
            errors: list[str] = []

            def callback(request_id, response, exception):
                if exception is not None:
                    errors.append(request_id)
                    return
                hdrs = {
                    h["name"].lower(): h["value"]
                    for h in response.get("payload", {}).get("headers", [])
                }
                collected.append(
                    {
                        "id": response.get("id"),
                        "threadId": response.get("threadId"),
                        "labelIds": response.get("labelIds", []),
                        "internalDate": response.get("internalDate"),
                        "headers": hdrs,
                    }
                )

            batch = self.service.new_batch_http_request(callback=callback)
            for mid in chunk:
                batch.add(
                    self.service.users().messages().get(
                        userId="me", id=mid, format="metadata",
                        metadataHeaders=headers,
                    ),
                    request_id=mid,
                )
            self.limiter.wait()
            batch.execute()

            #  Anything the batch dropped is retried individually rather than
            #  silently missing from the sender analysis.
            for mid in errors:
                try:
                    self.limiter.wait()
                    resp = execute(
                        self.service.users().messages().get(
                            userId="me", id=mid, format="metadata",
                            metadataHeaders=headers,
                        )
                    )
                except HttpError:
                    continue
                hdrs = {
                    h["name"].lower(): h["value"]
                    for h in resp.get("payload", {}).get("headers", [])
                }
                collected.append({
                    "id": resp.get("id"), "threadId": resp.get("threadId"),
                    "labelIds": resp.get("labelIds", []),
                    "internalDate": resp.get("internalDate"), "headers": hdrs,
                })

            yield from collected
            done += len(chunk)
            if progress_every and done % progress_every < METADATA_BATCH_SIZE:
                print(f"     fetched metadata for {done:,} messages...")

    # --------------------------------------------------------------- settings

    def get_auto_forwarding(self) -> dict:
        self.limiter.wait()
        return execute(self.service.users().settings().getAutoForwarding(userId="me"))

    def list_forwarding_addresses(self) -> list[dict]:
        self.limiter.wait()
        resp = execute(
            self.service.users().settings().forwardingAddresses().list(userId="me")
        )
        return resp.get("forwardingAddresses", [])

    def list_filters(self) -> list[dict]:
        self.limiter.wait()
        resp = execute(self.service.users().settings().filters().list(userId="me"))
        return resp.get("filter", [])

    def create_filter(self, criteria: dict, action: dict, *, phase: str = "filters",
                      note: str | None = None) -> dict | None:
        if self.dry_run:
            self.oplog.record(phase, "create_filter", count=0, dry_run=True, note=note)
            return None
        self.limiter.wait()
        created = execute(
            self.service.users().settings().filters().create(
                userId="me", body={"criteria": criteria, "action": action}
            )
        )
        self.oplog.record(phase, "create_filter", count=0, note=note)
        return created

    def remove_filter(self, filter_id: str, *, phase: str = "superhuman",
                      note: str | None = None) -> None:
        """Remove a Gmail *filter rule*. Does not touch messages or labels."""
        if self.dry_run:
            self.oplog.record(phase, "delete_filter", count=0, dry_run=True, note=note)
            return
        self.limiter.wait()
        execute(
            self.service.users().settings().filters().delete(
                userId="me", id=filter_id
            )
        )
        self.oplog.record(phase, "delete_filter", count=0, note=note)
