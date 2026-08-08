"""The safety rules from the brief, tested as behaviour rather than intent."""

import pytest

from gmail_rescue.api import (
    BATCH_MODIFY_CHUNK, GmailClient, HARDEN_TERMS, SafetyViolation, chunked,
    harden_query,
)
from gmail_rescue.oplog import OpLog

from .fake_gmail import FakeGmail, make_message


@pytest.fixture
def client(tmp_path):
    fake = FakeGmail(messages=[make_message("m1")])
    return GmailClient(fake, "test", OpLog("test", str(tmp_path), echo=False),
                       calls_per_second=0)


class TestHardenQuery:
    def test_adds_every_exclusion(self):
        hardened = harden_query("in:inbox category:promotions")
        for term in HARDEN_TERMS:
            assert term in hardened

    def test_starred_is_always_excluded(self):
        # "Never modify anything that is starred" reduces to this one term.
        assert "-is:starred" in harden_query("in:inbox")

    def test_sent_and_draft_excluded(self):
        hardened = harden_query("is:unread")
        assert "-in:sent" in hardened and "-in:drafts" in hardened

    def test_spam_and_trash_excluded(self):
        hardened = harden_query("is:unread")
        assert "-in:spam" in hardened and "-in:trash" in hardened

    def test_idempotent(self):
        once = harden_query("in:inbox")
        assert harden_query(once) == once

    def test_empty_query_still_hardened(self):
        assert "-is:starred" in harden_query("")

    def test_preserves_original_terms(self):
        assert harden_query("in:inbox category:social").startswith(
            "in:inbox category:social")


class TestChunking:
    @pytest.mark.parametrize("total,expected_chunks", [
        (0, 0), (1, 1), (999, 1), (1000, 1), (1001, 2), (2500, 3), (5000, 5),
    ])
    def test_chunk_counts(self, total, expected_chunks):
        chunks = chunked(list(range(total)), BATCH_MODIFY_CHUNK)
        assert len(chunks) == expected_chunks

    def test_no_chunk_exceeds_the_api_maximum(self):
        for chunk in chunked(list(range(4321)), BATCH_MODIFY_CHUNK):
            assert len(chunk) <= 1000

    def test_nothing_is_lost(self):
        items = list(range(2500))
        assert [x for c in chunked(items, BATCH_MODIFY_CHUNK) for x in c] == items

    def test_batch_modify_chunks_at_1000(self, tmp_path):
        fake = FakeGmail(messages=[make_message(f"m{i}") for i in range(2500)])
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        calls_per_second=0)
        ids = [f"m{i}" for i in range(2500)]
        c.batch_modify(ids, remove_label_ids=["INBOX"], phase="p", action="a")
        assert fake.batch_modify_chunk_sizes == [1000, 1000, 500]

    def test_invalid_chunk_size_rejected(self):
        with pytest.raises(ValueError):
            chunked([1, 2, 3], 0)


class TestProtectedLabels:
    @pytest.mark.parametrize("label", ["STARRED", "SENT", "DRAFT", "SPAM", "TRASH"])
    def test_cannot_be_removed(self, client, label):
        with pytest.raises(SafetyViolation):
            client.batch_modify(["m1"], remove_label_ids=[label],
                                phase="p", action="a")

    @pytest.mark.parametrize("label", ["SPAM", "TRASH"])
    def test_cannot_be_added(self, client, label):
        with pytest.raises(SafetyViolation):
            client.batch_modify(["m1"], add_label_ids=[label], phase="p", action="a")

    def test_inbox_removal_is_allowed(self, client):
        # Archiving is exactly this and must keep working.
        client.batch_modify(["m1"], remove_label_ids=["INBOX"], phase="p", action="a")
        assert "INBOX" not in client.service.messages["m1"]["labelIds"]

    def test_noop_modify_rejected(self, client):
        with pytest.raises(ValueError):
            client.batch_modify(["m1"], phase="p", action="a")


class TestLabelDeletion:
    @pytest.mark.parametrize("name", [
        "01_VIP", "Newsletters", "Finances", "INBOX", "Superhuman",
        "My [Superhuman] notes",
    ])
    def test_refuses_non_superhuman_labels(self, client, name):
        with pytest.raises(SafetyViolation):
            client.delete_superhuman_label(name)

    def test_allows_superhuman_prefixed(self, tmp_path):
        fake = FakeGmail(labels={"[Superhuman]/AI/Marketing":
                                 {"id": "L30", "name": "[Superhuman]/AI/Marketing"}})
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        calls_per_second=0)
        assert c.delete_superhuman_label("[Superhuman]/AI/Marketing") is True
        assert "[Superhuman]/AI/Marketing" not in fake.labels

    def test_deleting_a_label_keeps_the_messages(self, tmp_path):
        fake = FakeGmail(
            messages=[make_message("m1", labels=["INBOX", "L30"])],
            labels={"[Superhuman]/AI/News": {"id": "L30",
                                             "name": "[Superhuman]/AI/News"}},
        )
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        calls_per_second=0)
        c.delete_superhuman_label("[Superhuman]/AI/News")
        assert "m1" in fake.messages
        assert "INBOX" in fake.messages["m1"]["labelIds"]


class TestOpLog:
    def test_records_ids_for_undo(self, client, tmp_path):
        client.batch_modify(["m1"], remove_label_ids=["INBOX"],
                            phase="phase2", action="archive")
        records = OpLog.read(str(tmp_path / "oplog.test.jsonl"))
        assert records[0]["message_ids"] == ["m1"]
        assert records[0]["remove_labels"] == ["INBOX"]

    def test_flags_operations_over_5000(self, tmp_path):
        fake = FakeGmail(messages=[make_message(f"m{i}") for i in range(5001)])
        log = OpLog("t", str(tmp_path), echo=False)
        c = GmailClient(fake, "t", log, calls_per_second=0)
        c.batch_modify([f"m{i}" for i in range(5001)],
                       remove_label_ids=["INBOX"], phase="p", action="a")
        assert len(log.large_ops()) == 1

    def test_does_not_flag_exactly_5000(self, tmp_path):
        fake = FakeGmail(messages=[make_message(f"m{i}") for i in range(5000)])
        log = OpLog("t", str(tmp_path), echo=False)
        c = GmailClient(fake, "t", log, calls_per_second=0)
        c.batch_modify([f"m{i}" for i in range(5000)],
                       remove_label_ids=["INBOX"], phase="p", action="a")
        assert log.large_ops() == []

    def test_dry_run_does_not_mutate(self, tmp_path):
        fake = FakeGmail(messages=[make_message("m1")])
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        dry_run=True, calls_per_second=0)
        c.batch_modify(["m1"], remove_label_ids=["INBOX"], phase="p", action="a")
        assert "INBOX" in fake.messages["m1"]["labelIds"]
        assert fake.batch_modify_chunk_sizes == []


class TestListing:
    def test_pages_through_everything(self, tmp_path):
        fake = FakeGmail(messages=[make_message(f"m{i}") for i in range(1200)])
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        calls_per_second=0)
        assert len(c.list_message_ids("in:inbox")) == 1200

    def test_starred_excluded_from_mutating_queries(self, tmp_path):
        fake = FakeGmail(messages=[
            make_message("plain", labels=["INBOX"]),
            make_message("starred", labels=["INBOX", "STARRED"]),
        ])
        c = GmailClient(fake, "t", OpLog("t", str(tmp_path), echo=False),
                        calls_per_second=0)
        assert c.list_message_ids("in:inbox") == ["plain"]
