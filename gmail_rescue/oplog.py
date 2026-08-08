"""Append-only operation log.

Every query we run and every message we touch is recorded here before the run
moves on. Two reasons this exists:

  1. The brief requires logging every query and the count of messages it touched.
  2. At 26,000 messages, being able to answer "what exactly did it do at 14:32?"
     and to reverse it is worth the few megabytes. `undo` reads this file.

Format is JSON Lines: one self-contained JSON object per line, so a crashed run
still leaves a valid, readable log up to the point of failure.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class OpRecord:
    """One logged operation. `message_ids` is what makes undo possible."""

    op_id: str
    account: str
    phase: str
    action: str
    query: str | None
    add_labels: list[str] = field(default_factory=list)
    remove_labels: list[str] = field(default_factory=list)
    count: int = 0
    message_ids: list[str] = field(default_factory=list)
    dry_run: bool = False
    flagged_large: bool = False
    note: str | None = None
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class OpLog:
    """Writes OpRecords to reports/oplog.<account>.jsonl."""

    #  The brief's threshold: any single operation touching more than this many
    #  messages gets printed, proceeds anyway, and is flagged in the final report.
    LARGE_OP_THRESHOLD = 5000

    #  Operations that act on labels or filters rather than on messages.
    NON_MESSAGE_ACTIONS = frozenset({
        "create_label", "delete_label", "create_filter", "delete_filter",
    })

    def __init__(self, account: str, reports_dir: str = "reports", echo: bool = True):
        self.account = account
        self.path = os.path.join(reports_dir, f"oplog.{account}.jsonl")
        self.echo = echo
        self.records: list[OpRecord] = []
        os.makedirs(reports_dir, exist_ok=True)

    def record(
        self,
        phase: str,
        action: str,
        query: str | None = None,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
        message_ids: list[str] | None = None,
        count: int | None = None,
        dry_run: bool = False,
        note: str | None = None,
    ) -> OpRecord:
        ids = list(message_ids or [])
        n = count if count is not None else len(ids)
        rec = OpRecord(
            op_id=uuid.uuid4().hex[:12],
            account=self.account,
            phase=phase,
            action=action,
            query=query,
            add_labels=list(add_labels or []),
            remove_labels=list(remove_labels or []),
            count=n,
            message_ids=ids,
            dry_run=dry_run,
            flagged_large=n > self.LARGE_OP_THRESHOLD,
            note=note,
        )
        self.records.append(rec)

        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(rec.to_json() + "\n")

        if self.echo:
            prefix = "[dry-run] " if dry_run else ""
            label = f"{prefix}{phase}/{action}"
            if action in self.NON_MESSAGE_ACTIONS:
                #  Label and filter operations touch no mail; printing
                #  "0 messages" next to them reads like a failure.
                print(f"  {label:<38} {note or ''}")
            else:
                detail = f'q="{query}"' if query else ""
                print(f"  {label:<38} {n:>7,} messages  {detail}")
            if rec.flagged_large:
                print(
                    f"  !! LARGE OPERATION: {n:,} messages exceeds "
                    f"{self.LARGE_OP_THRESHOLD:,}. Proceeding; flagged in after.md."
                )
        return rec

    def large_ops(self) -> list[OpRecord]:
        return [r for r in self.records if r.flagged_large]

    def total_touched(self) -> int:
        return sum(r.count for r in self.records if not r.dry_run)

    @staticmethod
    def read(path: str) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        out = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
