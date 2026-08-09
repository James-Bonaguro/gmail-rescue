"""Command line entry point.

    python -m gmail_rescue <command> --account personal|business

Run `python -m gmail_rescue --help` for the full list. The intended order is
documented in README.md:

    auth → preflight → diagnose → cleanup → filters → report
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import ACCOUNTS, __version__
from . import cleanup as cleanup_mod
from . import diagnose as diagnose_mod
from . import filters as filters_mod
from . import report as report_mod
from .api import GmailClient
from .oplog import OpLog

REPORTS_DIR = "reports"
CONFIG_PATH = "config/domains.json"


def _client(args, dry_run: bool = False) -> GmailClient:
    from .auth import get_service, verify_scopes, authorize

    creds = authorize(args.account)
    missing = verify_scopes(creds)
    if missing:
        print("Your saved token is missing required permissions:")
        for scope in missing:
            print(f"  - {scope}")
        print(f"\nRe-run: python -m gmail_rescue auth --account {args.account} --force")
        raise SystemExit(1)

    service = get_service(args.account)
    oplog = OpLog(args.account, REPORTS_DIR)
    return GmailClient(service, args.account, oplog,
                       dry_run=dry_run or getattr(args, "dry_run", False))


# ------------------------------------------------------------------ commands


def cmd_auth(args) -> int:
    from .auth import get_service

    service = get_service(args.account, force_auth=args.force)
    profile = service.users().getProfile(userId="me").execute()
    address = profile.get("emailAddress")
    print(f"\n  Authorised: {address}")
    print(f"  Token saved to tokens/{args.account}.json")

    from .auth import ACCOUNT_HINTS

    expected = ACCOUNT_HINTS.get(args.account)
    if expected and address and address.lower() != expected.lower():
        print(f"\n  !! You signed in as {address}, but --account {args.account}")
        print(f"     is meant to be {expected}.")
        print(f"     Re-run with --force and pick the other account.")
        return 1
    return 0


def cmd_preflight(args) -> int:
    client = _client(args, dry_run=True)
    cleanup_mod.preflight(client, args.account)
    print("\n  Nothing was modified. If those numbers look right, run:")
    print(f"    python -m gmail_rescue cleanup --account {args.account}")
    return 0


def cmd_diagnose(args) -> int:
    client = _client(args, dry_run=True)
    summary = diagnose_mod.run(
        client, args.account, days=args.days, max_harvest=args.max_harvest,
        reports_dir=REPORTS_DIR,
    )
    hits = summary.get("superhuman_active_hits") or []
    if hits:
        print("\n  !! WARNING: [Superhuman] labels are still being applied to new")
        print("     mail. A leftover Gmail filter is doing it. Run cleanup to")
        print("     remove those filters before trusting any labelling.")
    return 0


def cmd_cleanup(args) -> int:
    client = _client(args)
    config = cleanup_mod.load_config(CONFIG_PATH)

    #  The Superhuman gate: if anything has been labelled since this run began,
    #  a filter is still live and labelling work must not proceed.
    started = int(time.time())
    hits = diagnose_mod.check_superhuman_activity(client, started - 300)
    if hits and not args.ignore_superhuman_gate:
        print("\n  !! STOPPING: [Superhuman] labels were applied to mail received")
        print("     in the last five minutes. That means a Gmail filter is still")
        print("     live and actively labelling.")
        for h in hits:
            print(f"       {h['label']}: {h['count']} recent message(s)")
        print("\n     Superhuman filter removal is safe and is the fix. Re-run with")
        print("     --ignore-superhuman-gate to proceed (it removes those filters")
        print("     first, before any labelling).")
        return 2

    if args.account == "personal":
        summary = cleanup_mod.run_personal(client, config, reports_dir=REPORTS_DIR)
    else:
        summary = cleanup_mod.run_business(client, config, reports_dir=REPORTS_DIR)

    path = os.path.join(REPORTS_DIR, f"cleanup.{args.account}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    large = client.oplog.large_ops()
    print(f"\n  Touched {client.oplog.total_touched():,} messages total.")
    if large:
        print(f"  {len(large)} operation(s) exceeded 5,000 messages "
              f"(flagged in after.md).")
    print(f"  Wrote {path}")
    return 0


def cmd_filters(args) -> int:
    client = _client(args)
    config = cleanup_mod.load_config(CONFIG_PATH)
    spec_path = f"config/filters.{args.account}.json"

    if args.use_saved and os.path.exists(spec_path):
        spec = filters_mod.load(spec_path)
        print(f"  Using saved filter set from {spec_path}")
    else:
        derived = _derive_newsletters(args.account, config)
        if args.account == "personal":
            spec = filters_mod.build_personal(config, derived)
        else:
            spec = filters_mod.build_business(config, derived)
        filters_mod.save(spec, spec_path)
        print(f"  Wrote {spec_path} ({len(spec['filters'])} filters, "
              f"{len(derived)} derived from your data)")

    result = filters_mod.apply(client, spec)
    path = os.path.join(REPORTS_DIR, f"filters.{args.account}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)
    return 0


def _derive_newsletters(account: str, config: dict) -> list[tuple[str, str]]:
    """Find newsletter domains in the account's own 90-day harvest."""
    from .senders import aggregate, derive_newsletter_domains

    cache = diagnose_mod.cache_path(account, REPORTS_DIR)
    if not os.path.exists(cache):
        print(f"  No metadata cache at {cache}; skipping derived newsletters.")
        print(f"  (Run `diagnose --account {account}` first to enable them.)")
        return []

    metas = []
    with open(cache, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                metas.append(json.loads(line))

    corr_path = os.path.join(REPORTS_DIR, f"correspondents.{account}.json")
    correspondents: set[str] = set()
    if os.path.exists(corr_path):
        with open(corr_path, encoding="utf-8") as fh:
            correspondents = set(json.load(fh))

    acct = config.get(account, {})
    excluded = set(config.get("never_auto_classify", []))
    for key in ("banks", "promotional", "receipts", "platform", "collab",
                "newsletters"):
        excluded |= set(acct.get(key, []))

    return derive_newsletter_domains(aggregate(metas), correspondents, excluded)


def cmd_report(args) -> int:
    accounts: dict = {}
    for account in ACCOUNTS:
        before = report_mod.load_before(account, REPORTS_DIR)
        cleanup_path = os.path.join(REPORTS_DIR, f"cleanup.{account}.json")
        filters_path = os.path.join(REPORTS_DIR, f"filters.{account}.json")
        if not before and not os.path.exists(cleanup_path):
            continue

        after = {}
        if not args.offline:
            try:
                ns = argparse.Namespace(account=account, dry_run=True)
                after = report_mod.collect_after(_client(ns, dry_run=True), account)
            except SystemExit:
                raise
            except Exception as err:
                print(f"  Could not re-count {account} live: {err}")

        accounts[account] = {
            "before": before,
            "after": after,
            "cleanup": _load_json(cleanup_path),
            "filters": _load_json(filters_path),
            "oplog": report_mod.load_oplog(account, REPORTS_DIR),
        }

    if not accounts:
        print("Nothing to report on yet. Run `diagnose` first.")
        return 1

    path = report_mod.write(accounts, REPORTS_DIR)
    print(f"\n  Wrote {path}")
    return 0


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cmd_undo(args) -> int:
    """Reverse one logged operation by re-adding what it removed."""
    records = report_mod.load_oplog(args.account, REPORTS_DIR)
    match = next((r for r in records if r["op_id"] == args.op), None)
    if not match:
        print(f"No operation {args.op!r} in reports/oplog.{args.account}.jsonl")
        return 1
    if match.get("dry_run"):
        print("That operation was a dry run; there is nothing to undo.")
        return 0
    if not match.get("message_ids"):
        print("That operation recorded no message ids (label or filter change).")
        print("Undo only reverses message label changes.")
        return 1

    client = _client(args)
    print(f"  Reversing {match['phase']}/{match['action']} "
          f"({match['count']:,} messages)")
    client.batch_modify(
        match["message_ids"],
        add_label_ids=match.get("remove_labels") or None,
        remove_label_ids=match.get("add_labels") or None,
        phase="undo", action=f"undo_{match['action']}",
        note=f"reversing op {args.op}",
    )
    print("  Done.")
    return 0


def cmd_run_all(args) -> int:
    for step in (cmd_diagnose, cmd_cleanup, cmd_filters):
        code = step(args)
        if code:
            return code
    return cmd_report(argparse.Namespace(offline=False))


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail_rescue",
        description="Two-account Gmail cleanup. Never deletes mail.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def with_account(p):
        p.add_argument("--account", required=True, choices=ACCOUNTS)
        return p

    p = with_account(sub.add_parser("auth", help="one-time browser sign-in"))
    p.add_argument("--force", action="store_true",
                   help="re-run the browser flow even if a token exists")
    p.set_defaults(func=cmd_auth)

    p = with_account(sub.add_parser(
        "preflight", help="count what cleanup would touch, change nothing"))
    p.set_defaults(func=cmd_preflight)

    p = with_account(sub.add_parser("diagnose", help="Phase 1, read-only"))
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--max-harvest", type=int, default=40000)
    p.set_defaults(func=cmd_diagnose)

    p = with_account(sub.add_parser("cleanup", help="Phase 2/3"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ignore-superhuman-gate", action="store_true",
                   help="proceed even if Superhuman filters are still live")
    p.set_defaults(func=cmd_cleanup)

    p = with_account(sub.add_parser("filters", help="Phase 4"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--use-saved", action="store_true",
                   help="apply config/filters.<account>.json as-is")
    p.set_defaults(func=cmd_filters)

    p = sub.add_parser("report", help="Phase 5, writes reports/after.md")
    p.add_argument("--offline", action="store_true",
                   help="skip the live re-count; use saved data only")
    p.set_defaults(func=cmd_report)

    p = with_account(sub.add_parser("undo", help="reverse one logged operation"))
    p.add_argument("--op", required=True, help="op_id from the oplog")
    p.set_defaults(func=cmd_undo)

    p = with_account(sub.add_parser(
        "run-all", help="diagnose, cleanup, filters, report in order"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--ignore-superhuman-gate", action="store_true")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--max-harvest", type=int, default=40000)
    p.add_argument("--use-saved", action="store_true")
    p.set_defaults(func=cmd_run_all)

    return parser


def main(argv=None) -> int:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted. Work already done is logged in reports/oplog.*.jsonl")
        return 130


if __name__ == "__main__":
    sys.exit(main())
