"""Pure parsing logic — the part most likely to be wrong on real headers."""

import pytest

from gmail_rescue.senders import (
    aggregate, derive_newsletter_domains, edition_key, extract_address,
    extract_display_name, extract_domain, is_one_click, parse_list_unsubscribe,
    recipients_of, top_senders,
)

from .fake_gmail import make_message


def _meta(msg):
    return {"id": msg["id"], "labelIds": msg["labelIds"],
            "headers": {k.lower(): v for k, v in msg["headers"].items()}}


class TestAddressParsing:
    @pytest.mark.parametrize("header,expected", [
        ("TLDR AI <ai@tldrnewsletter.com>", "ai@tldrnewsletter.com"),
        ("ai@tldrnewsletter.com", "ai@tldrnewsletter.com"),
        ('"Brew, Morning" <crew@morningbrew.com>', "crew@morningbrew.com"),
        ("MiXeD@CaSe.CoM", "mixed@case.com"),
        ("", ""),
    ])
    def test_extract_address(self, header, expected):
        assert extract_address(header) == expected

    @pytest.mark.parametrize("header,expected", [
        ("TLDR AI <ai@tldrnewsletter.com>", "tldrnewsletter.com"),
        ("x@e.lifetime.life", "e.lifetime.life"),
        ("no-at-sign", ""),
        ("trailing@dot.com.", "dot.com"),
    ])
    def test_extract_domain(self, header, expected):
        assert extract_domain(header) == expected

    def test_subdomains_stay_distinct(self):
        # e.lifetime.life and lifetime.life are different senders with
        # different unsubscribe links. Collapsing them would be wrong.
        assert extract_domain("a@e.lifetime.life") != extract_domain("a@lifetime.life")

    def test_display_name(self):
        assert extract_display_name("TLDR  AI <ai@x.com>") == "TLDR AI"
        assert extract_display_name("<ai@x.com>") == ""

    def test_recipients_of_collects_all_fields(self):
        headers = {"to": "a@x.com, B@x.com", "cc": "c@y.com", "bcc": "d@z.com"}
        assert set(recipients_of(headers)) == {"a@x.com", "b@x.com",
                                               "c@y.com", "d@z.com"}


class TestListUnsubscribe:
    def test_both_forms(self):
        got = parse_list_unsubscribe("<mailto:u@x.com>, <https://x.com/u?i=1>")
        assert got == {"http": "https://x.com/u?i=1", "mailto": "mailto:u@x.com"}

    def test_http_only(self):
        assert parse_list_unsubscribe("<https://x.com/u>")["mailto"] is None

    def test_mailto_only(self):
        got = parse_list_unsubscribe("<mailto:unsub@x.com?subject=stop>")
        assert got["http"] is None
        assert got["mailto"].startswith("mailto:")

    def test_malformed_without_brackets(self):
        # Real senders ship this. Falling over would drop them from the report.
        assert parse_list_unsubscribe("https://x.com/u")["http"] == "https://x.com/u"

    def test_empty(self):
        assert parse_list_unsubscribe("") == {"http": None, "mailto": None}

    def test_first_http_wins(self):
        got = parse_list_unsubscribe("<https://a.com/1>, <https://b.com/2>")
        assert got["http"] == "https://a.com/1"

    @pytest.mark.parametrize("value,expected", [
        ("List-Unsubscribe=One-Click", True),
        ("list-unsubscribe=one-click", True),
        ("", False),
        (None, False),
    ])
    def test_one_click(self, value, expected):
        assert is_one_click(value) is expected


class TestEditionSplitting:
    def test_display_name_preferred(self):
        assert edition_key("TLDR AI <ai@tldrnewsletter.com>", "Anything",
                           "tldrnewsletter.com") == "TLDR AI"

    def test_falls_back_to_subject_prefix(self):
        assert edition_key("<x@tldrnewsletter.com>",
                           "TLDR Web Dev — React 20 ships",
                           "tldrnewsletter.com") == "TLDR Web Dev"

    def test_falls_back_to_domain(self):
        assert edition_key("<x@a.com>", "", "a.com") == "a.com"

    def test_editions_are_separate_buckets(self):
        msgs = [
            _meta(make_message("1", sender="ai@tldrnewsletter.com", name="TLDR AI",
                               unsubscribe="<https://x.com/ai>")),
            _meta(make_message("2", sender="web@tldrnewsletter.com",
                               name="TLDR Web Dev",
                               unsubscribe="<https://x.com/web>")),
            _meta(make_message("3", sender="ai@tldrnewsletter.com", name="TLDR AI",
                               unsubscribe="<https://x.com/ai>")),
        ]
        stats = aggregate(msgs)
        assert len(stats) == 2
        ai = stats["tldrnewsletter.com :: TLDR AI"]
        assert ai.total == 2
        # Each edition keeps its own link — the entire reason for splitting.
        assert ai.unsub_http == "https://x.com/ai"
        assert stats["tldrnewsletter.com :: TLDR Web Dev"].unsub_http == \
            "https://x.com/web"

    def test_non_split_domain_stays_whole(self):
        msgs = [_meta(make_message(str(i), sender="a@morningbrew.com",
                                   name=f"Brew {i}")) for i in range(3)]
        assert list(aggregate(msgs)) == ["morningbrew.com"]


class TestAggregate:
    def test_read_unread_split(self):
        msgs = [
            _meta(make_message("1", sender="a@x.com", labels=["INBOX", "UNREAD"])),
            _meta(make_message("2", sender="a@x.com", labels=["INBOX"])),
            _meta(make_message("3", sender="a@x.com", labels=["INBOX"])),
        ]
        entry = aggregate(msgs)["x.com"]
        assert (entry.total, entry.unread, entry.read) == (3, 1, 2)

    def test_ranking(self):
        msgs = [_meta(make_message(f"a{i}", sender="a@a.com")) for i in range(5)]
        msgs += [_meta(make_message(f"b{i}", sender="b@b.com")) for i in range(9)]
        assert [s.key for s in top_senders(aggregate(msgs), 2)] == ["b.com", "a.com"]


class TestNewsletterDetection:
    def _stats(self, domain, n, with_unsub, sender=None):
        msgs = []
        for i in range(n):
            msgs.append(_meta(make_message(
                f"{domain}{i}", sender=sender or f"news@{domain}",
                unsubscribe="<https://x.com/u>" if i < with_unsub else None)))
        return aggregate(msgs)

    def test_qualifies(self):
        found = derive_newsletter_domains(self._stats("news.com", 10, 10),
                                          set(), set())
        assert [d for d, _ in found] == ["news.com"]

    def test_below_volume_threshold(self):
        assert derive_newsletter_domains(self._stats("news.com", 4, 4),
                                         set(), set()) == []

    def test_below_unsubscribe_ratio(self):
        # 7/10 = 70%, under the 80% bar.
        assert derive_newsletter_domains(self._stats("news.com", 10, 7),
                                         set(), set()) == []

    def test_correspondent_is_never_a_newsletter(self):
        # You have emailed this address, so it is a person, not a list.
        stats = self._stats("news.com", 10, 10, sender="chris@news.com")
        assert derive_newsletter_domains(stats, {"chris@news.com"}, set()) == []

    def test_excluded_domain_skipped(self):
        assert derive_newsletter_domains(self._stats("chase.com", 10, 10),
                                         set(), {"chase.com"}) == []

    def test_boundary_exactly_at_thresholds(self):
        # 5 messages, 80% — both exactly on the line, so both must pass.
        assert derive_newsletter_domains(self._stats("news.com", 5, 4),
                                         set(), set()) != []
