"""Structural proof that this tool cannot delete mail.

Behavioural tests show the code does not delete today. This file shows it
cannot start deleting tomorrow without someone deliberately defeating a test.
"""

import ast
import pathlib
import re

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "gmail_rescue"

#  Method names that destroy mail.
FORBIDDEN_METHODS = {"batchDelete", "trash", "untrash", "delete"}

#  `delete` alone is ambiguous: labels().delete and filters().delete are both
#  permitted and necessary -- deleting a label never deletes messages, and
#  removing a filter rule touches no mail at all. Everything else named delete
#  is forbidden. batchDelete/trash/untrash are forbidden unconditionally.
DELETE_ALLOWED_ON = {"labels", "filters"}


def source_files():
    return sorted(PACKAGE.glob("*.py"))


def _receiver_name(node: ast.Attribute) -> str | None:
    """For `x.labels().delete`, return 'labels'."""
    value = node.value
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        return value.func.attr
    if isinstance(value, ast.Attribute):
        return value.attr
    return None


def find_destructive_calls(path: pathlib.Path) -> list[str]:
    """Walk the AST rather than grepping text.

    A regex over source lines also matches prose in docstrings and comments,
    which made this test fail on its own explanation of what it forbids.
    """
    tree = ast.parse(path.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in FORBIDDEN_METHODS:
            continue
        if func.attr == "delete" and _receiver_name(func) in DELETE_ALLOWED_ON:
            continue
        offenders.append(f"{path.name}:{node.lineno}: .{func.attr}()")
    return offenders


def test_no_destructive_endpoint_in_source():
    offenders = [o for path in source_files() for o in find_destructive_calls(path)]
    assert not offenders, (
        "destructive Gmail endpoint referenced:\n" + "\n".join(offenders)
    )


def test_the_detector_actually_catches_things(tmp_path):
    """A safety test that never fails is not a safety test."""
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def go(service):\n"
        "    service.users().messages().delete(userId='me', id='x')\n"
        "    service.users().messages().batchDelete(userId='me')\n"
    )
    found = find_destructive_calls(bad)
    assert len(found) == 2

    good = tmp_path / "good.py"
    good.write_text(
        "def go(service):\n"
        "    service.users().labels().delete(userId='me', id='x')\n"
        "    service.users().settings().filters().delete(userId='me', id='y')\n"
    )
    assert find_destructive_calls(good) == []


def test_scopes_cannot_permanently_delete():
    from gmail_rescue.api import SCOPES

    # gmail.modify explicitly excludes permanent deletion; the full-access
    # scope (mail.google.com) would allow it and must never appear here.
    assert "https://mail.google.com/" not in SCOPES
    assert all("gmail." in s for s in SCOPES)


def test_only_two_scopes_requested():
    from gmail_rescue.api import SCOPES

    assert set(SCOPES) == {
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
    }


def test_label_deletion_is_gated_in_one_place():
    """Only delete_superhuman_label may call labels().delete."""
    hits = []
    for path in source_files():
        text = path.read_text()
        if "labels().delete" in text:
            hits.append(path.name)
    assert hits == ["api.py"], f"labels().delete leaked into {hits}"


def test_archive_never_removes_more_than_inbox_and_unread():
    """archive() is the only bulk-removal helper; keep its blast radius fixed."""
    from gmail_rescue.api import GmailClient
    import inspect

    src = inspect.getsource(GmailClient.archive)
    removed = set(re.findall(r'"([A-Z]+)"', src))
    assert removed <= {"INBOX", "UNREAD"}, removed
