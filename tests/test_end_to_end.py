"""Runs every phase against an in-memory mailbox.

This is the closest thing to a live rehearsal that is possible without
credentials: real code paths, real query strings, real chunking, real report
rendering — only the Gmail transport is substituted.
"""

import json

import pytest

from gmail_rescue import cleanup, diagnose, filters, report
from gmail_rescue.api import GmailClient
from gmail_rescue.guards import GuardSet
from gmail_rescue.oplog import OpLog

from .fake_gmail import FakeGmail, ForbiddenCall, make_message

VIP = "Label_20"
FINANCES = "Label_21"
SH_MARKETING = "Label_30"


def build_mailbox():
    msgs = []

    # --- machine mail the sweeps should take ------------------------------
    for i in range(30):
        msgs.append(make_message(
            f"promo{i}", sender=f"deals@popmenu.com", subject="50% off",
            labels=["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"], age_days=10,
            unsubscribe="<https://popmenu.com/u>", one_click=True))
    for i in range(20):
        msgs.append(make_message(
            f"upd{i}", sender="hello@deeperlearning.producthunt.com",
            name="Product Hunt Daily", subject="Today's launches",
            labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"], age_days=5,
            unsubscribe="<https://producthunt.com/u/daily>"))
    for i in range(10):
        msgs.append(make_message(
            f"soc{i}", sender="notify@linkedin.com",
            labels=["INBOX", "UNREAD", "CATEGORY_SOCIAL"], age_days=1))

    # --- TLDR, two editions, to exercise per-edition splitting ------------
    for i in range(25):
        msgs.append(make_message(
            f"tldrai{i}", sender="ai@tldrnewsletter.com", name="TLDR AI",
            subject="TLDR AI 2026-08-01",
            labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"], age_days=3,
            unsubscribe="<https://tldrnewsletter.com/u/ai>", one_click=True))
    for i in range(15):
        msgs.append(make_message(
            f"tldrweb{i}", sender="web@tldrnewsletter.com", name="TLDR Web Dev",
            subject="TLDR Web Dev 2026-08-01",
            labels=["INBOX", "UNREAD", "CATEGORY_UPDATES"], age_days=3,
            unsubscribe="<https://tldrnewsletter.com/u/web>", one_click=True))

    # --- stale unread primary, no guard: should be archived ---------------
    for i in range(12):
        msgs.append(make_message(
            f"stale{i}", sender=f"stranger{i}@random.com", subject="Cold pitch",
            labels=["INBOX", "UNREAD", "CATEGORY_PERSONAL"], age_days=120))

    # --- read primary backlog: the sweep ----------------------------------
    for i in range(40):
        msgs.append(make_message(
            f"oldread{i}", sender=f"someone{i}@elsewhere.com",
            labels=["INBOX", "CATEGORY_PERSONAL"], age_days=400))

    # --- things that MUST survive untouched -------------------------------
    msgs.append(make_message("starred1", sender="mum@family.com",
                             labels=["INBOX", "UNREAD", "STARRED"], age_days=200))
    msgs.append(make_message("vip1", sender="boss@client.com",
                             labels=["INBOX", "UNREAD", VIP], age_days=200))
    msgs.append(make_message("friend1", sender="dave@friend.com",
                             labels=["INBOX", "UNREAD"], age_days=200))
    msgs.append(make_message("recent1", sender="new@person.com",
                             labels=["INBOX", "UNREAD"], age_days=1))
    msgs.append(make_message("sent1", sender="me@example.com",
                             to="dave@friend.com", labels=["SENT"], age_days=30))
    msgs.append(make_message("draft1", sender="me@example.com",
                             labels=["DRAFT"], age_days=5))
    msgs.append(make_message("spam1", sender="bad@spam.com",
                             labels=["SPAM"], age_days=5))
    msgs.append(make_message("trash1", sender="x@x.com",
                             labels=["TRASH"], age_days=5))

    # --- archived unread: the badge kill ----------------------------------
    for i in range(50):
        msgs.append(make_message(f"phantom{i}", sender="old@news.com",
                                 labels=["UNREAD"], age_days=200))

    # --- bank mail: labelled, must stay in the inbox ----------------------
    for i in range(6):
        msgs.append(make_message(f"bank{i}", sender="alerts@chase.com",
                                 subject="Your statement",
                                 labels=["INBOX", "CATEGORY_UPDATES"], age_days=1))

    # --- still carrying a Superhuman label --------------------------------
    msgs.append(make_message("sh1", sender="x@marketing.com",
                             labels=["INBOX", SH_MARKETING], age_days=10))
    return msgs


@pytest.fixture
def env(tmp_path):
    fake = FakeGmail(
        messages=build_mailbox(),
        labels={
            "01_VIP": {"id": VIP, "name": "01_VIP"},
            "Finances": {"id": FINANCES, "name": "Finances"},
            "[Superhuman]/AI/Marketing": {"id": SH_MARKETING,
                                          "name": "[Superhuman]/AI/Marketing"},
        },
        filters=[{
            "id": "f_sh",
            "criteria": {"from": "marketing.com"},
            "action": {"addLabelIds": [SH_MARKETING]},
        }, {
            "id": "f_keep",
            "criteria": {"from": "chase.com"},
            "action": {"addLabelIds": [FINANCES]},
        }],
        auto_forwarding={"enabled": False},
    )
    log = OpLog("personal", str(tmp_path), echo=False)
    client = GmailClient(fake, "personal", log, calls_per_second=0)
    return fake, client, str(tmp_path)


class TestDiagnose:
    def test_is_read_only(self, env):
        fake, client, reports = env
        before = json.dumps(fake.messages, sort_keys=True)
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        assert json.dumps(fake.messages, sort_keys=True) == before

    def test_writes_both_report_formats(self, env, tmp_path):
        _, client, reports = env
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        assert (tmp_path / "diagnosis.personal.md").exists()
        assert (tmp_path / "diagnosis.personal.json").exists()
        assert (tmp_path / "metadata_cache.personal.jsonl").exists()

    def test_counts_and_categories(self, env):
        _, client, reports = env
        s = diagnose.run(client, "personal", days=90, reports_dir=reports)
        c = s["counts"]
        assert c["inbox_unread"] > 0
        assert c["unread_by_category"]["promotions"] == 30
        assert c["unread_by_category"]["social"] == 10

    def test_detects_superhuman_labels(self, env):
        _, client, reports = env
        s = diagnose.run(client, "personal", days=90, reports_dir=reports)
        assert s["superhuman_labels"] == ["[Superhuman]/AI/Marketing"]

    def test_report_renders_without_placeholders(self, env):
        _, client, reports = env
        s = diagnose.run(client, "personal", days=90, reports_dir=reports)
        md = diagnose.render(s)
        assert "# Diagnosis" in md
        assert "{" not in md.replace("{}", "")


class TestSuperhumanTeardown:
    def test_filter_removed_before_label(self, env):
        fake, client, _ = env
        result = cleanup.kill_superhuman(client)
        assert [f["id"] for f in result["filters_deleted"]] == ["f_sh"]
        assert result["labels_deleted"] == ["[Superhuman]/AI/Marketing"]
        order = [c for c in fake.calls if c.startswith(("deleteFilter", "deleteLabel"))]
        assert order.index("deleteFilter:f_sh") < order.index(
            "deleteLabel:[Superhuman]/AI/Marketing")

    def test_unrelated_filter_survives(self, env):
        fake, client, _ = env
        cleanup.kill_superhuman(client)
        assert [f["id"] for f in fake.filters] == ["f_keep"]

    def test_message_survives_label_deletion(self, env):
        fake, client, _ = env
        cleanup.kill_superhuman(client)
        assert "sh1" in fake.messages
        assert "INBOX" in fake.messages["sh1"]["labelIds"]


class TestFullCleanup:
    @pytest.fixture
    def done(self, env):
        fake, client, reports = env
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        config = cleanup.load_config("config/domains.json")
        summary = cleanup.run_personal(client, config, reports_dir=reports)
        return fake, client, reports, summary

    def test_starred_never_touched(self, done):
        fake, *_ = done
        assert set(fake.messages["starred1"]["labelIds"]) == {
            "INBOX", "UNREAD", "STARRED"}

    def test_vip_never_archived(self, done):
        fake, *_ = done
        assert "INBOX" in fake.messages["vip1"]["labelIds"]
        assert "UNREAD" in fake.messages["vip1"]["labelIds"]

    def test_correspondent_never_archived(self, done):
        # We have emailed dave@friend.com (sent1), so his stale unread stays.
        fake, *_ = done
        assert "INBOX" in fake.messages["friend1"]["labelIds"]

    def test_sent_and_draft_untouched(self, done):
        fake, *_ = done
        assert fake.messages["sent1"]["labelIds"] == ["SENT"]
        assert fake.messages["draft1"]["labelIds"] == ["DRAFT"]

    def test_spam_and_trash_untouched(self, done):
        fake, *_ = done
        assert fake.messages["spam1"]["labelIds"] == ["SPAM"]
        assert fake.messages["trash1"]["labelIds"] == ["TRASH"]

    def test_recent_mail_stays_in_inbox(self, done):
        fake, *_ = done
        assert "INBOX" in fake.messages["recent1"]["labelIds"]

    def test_promotions_archived(self, done):
        fake, *_ = done
        assert "INBOX" not in fake.messages["promo0"]["labelIds"]
        assert "UNREAD" not in fake.messages["promo0"]["labelIds"]

    def test_social_archived(self, done):
        fake, *_ = done
        assert "INBOX" not in fake.messages["soc0"]["labelIds"]

    def test_stale_unguarded_unread_archived(self, done):
        fake, *_ = done
        assert "INBOX" not in fake.messages["stale0"]["labelIds"]
        assert "UNREAD" not in fake.messages["stale0"]["labelIds"]

    def test_read_backlog_swept(self, done):
        fake, *_ = done
        assert "INBOX" not in fake.messages["oldread0"]["labelIds"]

    def test_badge_kill_clears_unread_without_moving(self, done):
        fake, *_ = done
        msg = fake.messages["phantom0"]
        assert "UNREAD" not in msg["labelIds"]
        assert "INBOX" not in msg["labelIds"]  # was already archived

    def test_bank_mail_labelled_and_kept_in_inbox(self, done):
        fake, *_ = done
        msg = fake.messages["bank0"]
        assert FINANCES in msg["labelIds"]
        assert "INBOX" in msg["labelIds"]

    def test_nothing_was_deleted(self, done):
        fake, *_ = done
        assert len(fake.messages) == len(build_mailbox())

    def test_inbox_unread_falls_under_fifty(self, done):
        fake, client, *_ = done
        remaining = client.list_message_ids("in:inbox is:unread", harden=False)
        assert len(remaining) < 50

    def test_oplog_captures_every_write(self, done):
        _, client, reports, _ = done
        records = OpLog.read(f"{reports}/oplog.personal.jsonl")
        assert records
        assert all("query" in r for r in records)
        touched = sum(r["count"] for r in records if r["action"].startswith("archive"))
        assert touched > 0


class TestGuards:
    def test_partition_separates_protected(self):
        guards = GuardSet(correspondents={"dave@friend.com"},
                          protected_label_ids={VIP})
        metas = [
            {"id": "a", "labelIds": [], "headers": {"from": "x@y.com"}},
            {"id": "b", "labelIds": [VIP], "headers": {"from": "x@y.com"}},
            {"id": "c", "labelIds": [], "headers": {"from": "dave@friend.com"}},
        ]
        actionable, protected = guards.partition(metas)
        assert [m["id"] for m in actionable] == ["a"]
        assert {m["id"] for m in protected} == {"b", "c"}


class TestFilters:
    def test_builds_and_applies(self, env):
        fake, client, reports = env
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [("leftclick.ai", "derived reason")])
        result = filters.apply(client, spec)
        assert len(result["created"]) == len(spec["filters"])
        assert any("Newsletters" in f["description"] for f in result["created"])

    def test_is_idempotent(self, env):
        _, client, _ = env
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [])
        filters.apply(client, spec)
        second = filters.apply(client, spec)
        assert second["created"] == []
        assert len(second["skipped"]) == len(spec["filters"])

    def test_derived_filters_carry_their_reasoning(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [("leftclick.ai", "10 msgs/90d")])
        derived = [f for f in spec["filters"] if f["source"] == "derived"]
        assert derived and derived[0]["why"]["leftclick.ai"] == "10 msgs/90d"

    def test_bank_filter_keeps_mail_in_inbox(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [])
        bank = next(f for f in spec["filters"] if f["key"].startswith("personal.banks"))
        assert "removeLabelIds" not in bank["action"]
        assert bank["action"]["addLabelNames"] == ["Finances"]

    def test_newsletter_filter_skips_inbox(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [])
        news = next(f for f in spec["filters"]
                    if f["key"].startswith("personal.newsletters"))
        assert news["action"]["removeLabelIds"] == ["INBOX"]

    def test_is_address_filter_present(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_personal(config, [])
        f = next(f for f in spec["filters"] if f["key"] == "personal.is_address")
        assert f["criteria"]["to"] == "james@intersectionstrategies.co"
        assert "removeLabelIds" not in f["action"]

    def test_business_platform_skips_inbox(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_business(config, [])
        f = next(f for f in spec["filters"] if f["key"].startswith("business.platform"))
        assert f["action"]["removeLabelIds"] == ["INBOX"]

    def test_business_receipts_stay_in_inbox(self):
        config = cleanup.load_config("config/domains.json")
        spec = filters.build_business(config, [])
        f = next(f for f in spec["filters"] if f["key"].startswith("business.receipts"))
        assert "removeLabelIds" not in f["action"]

    def test_signature_ignores_ordering(self):
        a = filters.signature({"from": "a.com"}, {"addLabelIds": ["1", "2"]})
        b = filters.signature({"from": "A.com"}, {"addLabelIds": ["2", "1"]})
        assert a == b


class TestReport:
    def test_renders_end_to_end(self, env, tmp_path):
        fake, client, reports = env
        before = diagnose.run(client, "personal", days=90, reports_dir=reports)
        config = cleanup.load_config("config/domains.json")
        summary = cleanup.run_personal(client, config, reports_dir=reports)
        spec = filters.build_personal(config, [])
        applied = filters.apply(client, spec)

        md = report.build({"personal": {
            "before": before,
            "after": report.collect_after(client, "personal"),
            "cleanup": summary,
            "filters": applied,
            "oplog": OpLog.read(f"{reports}/oplog.personal.jsonl"),
        }}, reports_dir=reports)

        assert "# Gmail rescue" in md
        assert "Nothing was deleted" in md
        assert "clearbriefco@gmail.com" in md
        assert "weekly workflow" in md.lower()
        assert "[Superhuman]/AI/Marketing" in md

    def test_unsubscribe_list_splits_editions(self, env, tmp_path):
        _, client, reports = env
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        rows = report.unsubscribe_candidates("personal", reports, 25)
        keys = [r.key for r in rows]
        assert "tldrnewsletter.com :: TLDR AI" in keys
        assert "tldrnewsletter.com :: TLDR Web Dev" in keys

    def test_unsubscribe_rows_carry_links(self, env, tmp_path):
        _, client, reports = env
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        rows = report.unsubscribe_candidates("personal", reports, 25)
        assert all(r.best_unsub for r in rows)
        ai = next(r for r in rows if r.key.endswith("TLDR AI"))
        assert ai.unsub_http == "https://tldrnewsletter.com/u/ai"
        assert ai.one_click is True

    def test_ranked_by_volume(self, env, tmp_path):
        _, client, reports = env
        diagnose.run(client, "personal", days=90, reports_dir=reports)
        rows = report.unsubscribe_candidates("personal", reports, 25)
        assert [r.total for r in rows] == sorted(
            (r.total for r in rows), reverse=True)


class TestBusiness:
    def test_creates_labels_and_preserves_existing(self, tmp_path):
        fake = FakeGmail(
            messages=[make_message("m1", labels=["INBOX"])],
            labels={"To respond": {"id": "Label_1", "name": "To respond"},
                    "Info Alias": {"id": "Label_2", "name": "Info Alias"}},
        )
        client = GmailClient(fake, "business",
                             OpLog("business", str(tmp_path), echo=False),
                             calls_per_second=0)
        config = cleanup.load_config("config/domains.json")
        summary = cleanup.run_business(client, config, reports_dir=str(tmp_path))

        for name in ("Clients", "Leads", "Admin", "Newsletters", "IS/Receipts 2026"):
            assert name in fake.labels
        # The two survivors of the label wipe are not [Superhuman] and must stay.
        assert "To respond" in fake.labels
        assert "Info Alias" in fake.labels
        assert set(summary["labels_created"]) >= {"Clients", "Leads", "Admin"}

    def test_nested_receipts_label_has_parent(self, tmp_path):
        fake = FakeGmail(messages=[make_message("m1")])
        client = GmailClient(fake, "business",
                             OpLog("business", str(tmp_path), echo=False),
                             calls_per_second=0)
        cleanup.run_business(client, cleanup.load_config("config/domains.json"),
                             reports_dir=str(tmp_path))
        assert "IS" in fake.labels and "IS/Receipts 2026" in fake.labels


def test_destructive_endpoints_are_never_called(env):
    """The fake raises on delete/trash; a full run must not trip it."""
    fake, client, reports = env
    diagnose.run(client, "personal", days=90, reports_dir=reports)
    config = cleanup.load_config("config/domains.json")
    cleanup.run_personal(client, config, reports_dir=reports)
    filters.apply(client, filters.build_personal(config, []))
    # If any phase had called them, ForbiddenCall would already have surfaced.
    with pytest.raises(ForbiddenCall):
        fake.users().messages().delete(userId="me", id="promo0")
