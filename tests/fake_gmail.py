"""An in-memory Gmail double good enough to run all five phases offline.

It implements the slice of the API this tool uses, including a small Gmail
query evaluator, so the end-to-end tests exercise the real code paths rather
than mocks that agree with whatever the code happens to do.

Any call to a delete or trash endpoint raises immediately -- that is the point.
"""

from __future__ import annotations

import re
import time

_LABEL_FOR_TOKEN = {
    "in:inbox": "INBOX",
    "in:sent": "SENT",
    "in:drafts": "DRAFT",
    "in:draft": "DRAFT",
    "in:chats": "CHAT",
    "in:spam": "SPAM",
    "in:trash": "TRASH",
    "is:unread": "UNREAD",
    "is:read": "!UNREAD",
    "is:starred": "STARRED",
    "category:primary": "CATEGORY_PERSONAL",
    "category:promotions": "CATEGORY_PROMOTIONS",
    "category:updates": "CATEGORY_UPDATES",
    "category:social": "CATEGORY_SOCIAL",
    "category:forums": "CATEGORY_FORUMS",
}

_DURATION = re.compile(r"^(\d+)([dmy])$")


class ForbiddenCall(AssertionError):
    """Raised if the code under test ever tries to delete or trash mail."""


def _duration_ms(value: str) -> int:
    m = _DURATION.match(value)
    if not m:
        return 0
    n, unit = int(m.group(1)), m.group(2)
    per = {"d": 86400, "m": 2592000, "y": 31536000}[unit]
    return n * per * 1000


def _tokenize(query: str) -> list[str]:
    """Split a query into terms, keeping parenthesised groups intact."""
    tokens, buf, depth = [], "", 0
    for ch in query:
        if ch == "(":
            depth += 1
            buf += ch
        elif ch == ")":
            depth -= 1
            buf += ch
        elif ch.isspace() and depth == 0:
            if buf:
                tokens.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        tokens.append(buf)
    return tokens


class FakeGmail:
    def __init__(self, messages=None, labels=None, filters=None,
                 auto_forwarding=None, forwarding_addresses=None):
        self.messages = {m["id"]: m for m in (messages or [])}
        self.labels = dict(labels or {})
        for sysname in ("INBOX", "UNREAD", "STARRED", "SENT", "DRAFT", "SPAM",
                        "TRASH", "CHAT", "IMPORTANT"):
            self.labels.setdefault(sysname, {"id": sysname, "name": sysname,
                                             "type": "system"})
        self.filters = list(filters or [])
        self.auto_forwarding = auto_forwarding or {"enabled": False}
        self.forwarding_addresses = list(forwarding_addresses or [])
        self._next_label = 1000
        self.calls: list[str] = []
        self.batch_modify_chunk_sizes: list[int] = []

    # ------------------------------------------------------------- matching

    @staticmethod
    def _header(msg: dict, name: str) -> str:
        """Case-insensitive header lookup.

        Real Gmail matches headers regardless of case, and messages in the
        wild use every capitalisation there is. A case-sensitive double here
        silently made every from: query return nothing.
        """
        target = name.lower()
        for key, value in msg.get("headers", {}).items():
            if key.lower() == target:
                return value or ""
        return ""

    def _match_term(self, msg: dict, term: str, now_ms: int) -> bool:
        if term.startswith("-"):
            return not self._match_term(msg, term[1:], now_ms)
        if term.startswith("(") and term.endswith(")"):
            inner = [t for t in _tokenize(term[1:-1]) if t.upper() != "OR"]
            return any(self._match_term(msg, t, now_ms) for t in inner)

        low = term.lower()
        labels = msg.get("labelIds", [])

        if low in _LABEL_FOR_TOKEN:
            want = _LABEL_FOR_TOKEN[low]
            if want.startswith("!"):
                return want[1:] not in labels
            return want in labels
        if low == "in:anywhere":
            return True
        if low.startswith("label:"):
            name = term.split(":", 1)[1].strip('"')
            lab = self.labels.get(name)
            return bool(lab and lab["id"] in labels)
        if low.startswith("older_than:"):
            return int(msg["internalDate"]) < now_ms - _duration_ms(low.split(":", 1)[1])
        if low.startswith("newer_than:"):
            return int(msg["internalDate"]) > now_ms - _duration_ms(low.split(":", 1)[1])
        if low.startswith("after:"):
            return int(msg["internalDate"]) > int(low.split(":", 1)[1]) * 1000
        if low.startswith("before:"):
            return int(msg["internalDate"]) < int(low.split(":", 1)[1]) * 1000
        if low.startswith("from:"):
            return low.split(":", 1)[1] in self._header(msg, "from").lower()
        if low.startswith("to:"):
            return low.split(":", 1)[1] in self._header(msg, "to").lower()
        if low.startswith("deliveredto:"):
            target = low.split(":", 1)[1]
            joined = " ".join(
                self._header(msg, h) for h in ("delivered-to", "to", "cc")
            ).lower()
            return target in joined
        if low.startswith("subject:"):
            return low.split(":", 1)[1] in self._header(msg, "subject").lower()
        return True  # unknown operators do not filter

    def search(self, query: str | None, label_ids=None) -> list[dict]:
        now_ms = int(time.time() * 1000)
        terms = [t for t in _tokenize(query or "") if t.upper() != "OR"]
        out = []
        for msg in self.messages.values():
            #  Gmail excludes SPAM and TRASH unless explicitly asked.
            if ("SPAM" in msg["labelIds"] or "TRASH" in msg["labelIds"]) and \
                    "in:anywhere" not in (query or "").lower():
                continue
            if label_ids and not all(l in msg["labelIds"] for l in label_ids):
                continue
            if all(self._match_term(msg, t, now_ms) for t in terms):
                out.append(msg)
        return out

    # ---------------------------------------------------------- API surface

    def users(self):
        return _Users(self)

    def new_batch_http_request(self, callback=None):
        return _Batch(callback)


class _Resp:
    def __init__(self, value):
        self._value = value

    def execute(self):
        return self._value


class _DeferredGet:
    """Mimics a request object that a batch can execute later."""

    def __init__(self, fake, message_id, headers):
        self.fake = fake
        self.message_id = message_id
        self.headers = headers

    def execute(self):
        msg = self.fake.messages.get(self.message_id)
        if msg is None:
            raise KeyError(self.message_id)
        wanted = {h.lower() for h in self.headers}
        return {
            "id": msg["id"],
            "threadId": msg.get("threadId", msg["id"]),
            "labelIds": list(msg["labelIds"]),
            "internalDate": str(msg["internalDate"]),
            "payload": {
                "headers": [
                    {"name": k, "value": v}
                    for k, v in msg["headers"].items() if k.lower() in wanted
                ]
            },
        }


class _Batch:
    def __init__(self, callback):
        self.callback = callback
        self.requests: list[tuple[str, _DeferredGet]] = []

    def add(self, request, request_id=None):
        self.requests.append((request_id, request))

    def execute(self):
        for request_id, request in self.requests:
            try:
                self.callback(request_id, request.execute(), None)
            except Exception as err:
                self.callback(request_id, None, err)


class _Users:
    def __init__(self, fake):
        self.fake = fake

    def getProfile(self, userId=None):
        self.fake.calls.append("getProfile")
        inbox = [m for m in self.fake.messages.values()
                 if "TRASH" not in m["labelIds"]]
        return _Resp({
            "emailAddress": "test@example.com",
            "messagesTotal": len(inbox),
            "threadsTotal": len({m.get("threadId", m["id"]) for m in inbox}),
        })

    def labels(self):
        return _Labels(self.fake)

    def messages(self):
        return _Messages(self.fake)

    def settings(self):
        return _Settings(self.fake)


class _Labels:
    def __init__(self, fake):
        self.fake = fake

    def list(self, userId=None):
        return _Resp({"labels": [
            {"id": l["id"], "name": n} for n, l in self.fake.labels.items()
        ]})

    def get(self, userId=None, id=None):
        name = next((n for n, l in self.fake.labels.items() if l["id"] == id), None)
        msgs = [m for m in self.fake.messages.values() if id in m["labelIds"]]
        unread = [m for m in msgs if "UNREAD" in m["labelIds"]]
        return _Resp({
            "id": id, "name": name,
            "messagesTotal": len(msgs), "messagesUnread": len(unread),
            "threadsTotal": len({m.get("threadId", m["id"]) for m in msgs}),
            "threadsUnread": len({m.get("threadId", m["id"]) for m in unread}),
        })

    def create(self, userId=None, body=None):
        self.fake._next_label += 1
        lid = f"Label_{self.fake._next_label}"
        self.fake.labels[body["name"]] = {"id": lid, "name": body["name"]}
        self.fake.calls.append(f"createLabel:{body['name']}")
        return _Resp({"id": lid, "name": body["name"]})

    def delete(self, userId=None, id=None):
        name = next((n for n, l in self.fake.labels.items() if l["id"] == id), None)
        if name:
            del self.fake.labels[name]
            for msg in self.fake.messages.values():
                if id in msg["labelIds"]:
                    msg["labelIds"].remove(id)
        self.fake.calls.append(f"deleteLabel:{name}")
        return _Resp({})


class _Messages:
    def __init__(self, fake):
        self.fake = fake

    def list(self, userId=None, q=None, maxResults=None, pageToken=None,
             labelIds=None, includeSpamTrash=False):
        matched = self.fake.search(q, labelIds)
        start = int(pageToken or 0)
        page = matched[start : start + (maxResults or 500)]
        out = {"messages": [{"id": m["id"]} for m in page],
               "resultSizeEstimate": len(matched)}
        nxt = start + len(page)
        if nxt < len(matched):
            out["nextPageToken"] = str(nxt)
        return _Resp(out)

    def get(self, userId=None, id=None, format=None, metadataHeaders=None):
        return _DeferredGet(self.fake, id, metadataHeaders or [])

    def batchModify(self, userId=None, body=None):
        ids = body.get("ids", [])
        self.fake.batch_modify_chunk_sizes.append(len(ids))
        add = body.get("addLabelIds", [])
        remove = body.get("removeLabelIds", [])
        for mid in ids:
            msg = self.fake.messages.get(mid)
            if not msg:
                continue
            for lid in add:
                if lid not in msg["labelIds"]:
                    msg["labelIds"].append(lid)
            for lid in remove:
                if lid in msg["labelIds"]:
                    msg["labelIds"].remove(lid)
        self.fake.calls.append(f"batchModify:{len(ids)}")
        return _Resp({})

    # --- endpoints that must never be reached -----------------------------

    def delete(self, **kw):
        raise ForbiddenCall("messages.delete must never be called")

    def batchDelete(self, **kw):
        raise ForbiddenCall("messages.batchDelete must never be called")

    def trash(self, **kw):
        raise ForbiddenCall("messages.trash must never be called")


class _Settings:
    def __init__(self, fake):
        self.fake = fake

    def getAutoForwarding(self, userId=None):
        return _Resp(self.fake.auto_forwarding)

    def forwardingAddresses(self):
        fake = self.fake

        class _FA:
            def list(self, userId=None):
                return _Resp({"forwardingAddresses": fake.forwarding_addresses})

        return _FA()

    def filters(self):
        fake = self.fake

        class _F:
            def list(self, userId=None):
                return _Resp({"filter": fake.filters})

            def create(self, userId=None, body=None):
                new = {"id": f"filter_{len(fake.filters) + 1}", **body}
                fake.filters.append(new)
                fake.calls.append("createFilter")
                return _Resp(new)

            def delete(self, userId=None, id=None):
                fake.filters = [f for f in fake.filters if f["id"] != id]
                fake.calls.append(f"deleteFilter:{id}")
                return _Resp({})

        return _F()


# ------------------------------------------------------------ test fixtures


def make_message(mid, *, sender="a@example.com", name="", subject="Hello",
                 labels=("INBOX",), age_days=1, unsubscribe=None,
                 one_click=False, to="me@example.com", thread=None):
    headers = {"From": f"{name} <{sender}>" if name else sender,
               "Subject": subject, "To": to}
    if unsubscribe:
        headers["List-Unsubscribe"] = unsubscribe
        if one_click:
            headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return {
        "id": mid,
        "threadId": thread or mid,
        "labelIds": list(labels),
        "internalDate": int((time.time() - age_days * 86400) * 1000),
        "headers": headers,
    }
