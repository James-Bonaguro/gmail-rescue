# gmail-rescue

Cleans up two Gmail accounts — `james.bonaguro@gmail.com` (personal) and
`james@intersectionstrategies.co` (business) — and keeps them clean with filters.

**It never deletes mail.** "Archive" means removing the `INBOX` label and
nothing else; every message stays in All Mail and stays searchable. Starred mail,
SENT, DRAFT, SPAM and TRASH are excluded from every operation. The OAuth scope it
requests (`gmail.modify`) does not include permanent deletion, so this is
enforced by Google, not just by the code.

---

## Two ways to do this. Pick one.

**If you want it fixed today with no setup**, read **[MANUAL.md](MANUAL.md)**.
Click-by-click instructions for doing the whole thing in your browser: the exact
searches to paste, what to click for each, every filter to create. About 45
minutes, nothing to install.

**If you want the sender analysis and the ranked unsubscribe list**, do
**[SETUP.md](SETUP.md)** first (~10 minutes, once) and then run the commands
below. This is the version that tells you which 25 senders are actually burying
you, with their unsubscribe links extracted and TLDR/Product Hunt broken out per
edition.

Both paths end in the same place. The scripted one shows its work.

---

## Why a script and not the Claude connector

The Gmail connector in Claude attaches **one account at a time**, can only label
one conversation per call, and cannot create a Gmail filter at all. This tool
holds a separate token per account, modifies 1,000 messages per call, and creates
filters through the settings API. That is the entire reason it exists.

It has to run on **your** machine: Google requires you to click "Allow" in a
browser, and returns that approval to an address that only exists on the computer
the browser is running on. Google retired the copy-paste flow in January 2023, so
there is no way to do this from a remote container.

---

## Runbook

After [SETUP.md](SETUP.md), run these in order. Do the personal account first.

```bash
# 1. See what is actually there. Read-only — changes nothing.
.venv/bin/python -m gmail_rescue diagnose --account personal

# 2. Count exactly what the cleanup would touch. Still changes nothing.
.venv/bin/python -m gmail_rescue preflight --account personal

# 3. Do it.
.venv/bin/python -m gmail_rescue cleanup --account personal

# 4. Install the filters that keep it clean.
.venv/bin/python -m gmail_rescue filters --account personal

# 5. Same four for business.
.venv/bin/python -m gmail_rescue diagnose  --account business
.venv/bin/python -m gmail_rescue preflight --account business
.venv/bin/python -m gmail_rescue cleanup   --account business
.venv/bin/python -m gmail_rescue filters   --account business

# 6. Write the handoff report covering both.
.venv/bin/python -m gmail_rescue report
```

**Read the `preflight` output before running `cleanup`.** It prints the exact
count for every operation. That is the go/no-go.

Add `--dry-run` to `cleanup` or `filters` to go through the motions and log
everything without writing to Gmail. `run-all` chains steps 1–4 if you trust it.

### Expect step 3 to take a while

The personal account has ~26,000 inbox messages. Applying the human-mail guards
means fetching one metadata record per candidate message, batched 50 at a time —
roughly 520 requests, **10 to 20 minutes**. It prints progress. If you interrupt
it, everything already done is in `reports/oplog.personal.jsonl` and re-running
picks up from the current state.

---

## What each phase does

| Phase | Command | Effect |
|---|---|---|
| 1 | `diagnose` | Profile, forwarding settings, filters, all labels with counts, unread by category, top 30 senders over 90 days, List-Unsubscribe counts. Writes `reports/diagnosis.<account>.md`. **Read-only.** |
| 2 | `cleanup --account personal` | Removes Superhuman filters then labels; archives promotions/updates >2d and all social; sweeps stale unread and read backlog >30d behind guards; clears phantom unread; labels bank mail `Finances`. |
| 3 | `cleanup --account business` | Creates `Clients`, `Leads`, `Admin`, `Newsletters`, `IS/Receipts 2026`; same archive passes; buckets receipts and platform mail from that account's own sender data. |
| 4 | `filters` | Creates the Gmail filters. Idempotent — running twice does not duplicate. |
| 5 | `report` | Writes `reports/after.md`: before/after numbers, labels and filters changed, top 25 unsubscribe candidates with links, weekly workflow. |

---

## The safety rules, and where they live

Every one of these is enforced in code and covered by a test:

- **Nothing is deleted.** No delete, trash or batchDelete call exists anywhere in
  the package — `tests/test_safety.py` parses the AST of every source file to
  prove it, and proves the detector works by running it against a known-bad file.
- **Starred, SENT, DRAFT, SPAM and TRASH are untouchable.** Every mutating query
  goes through `harden_query()` in `api.py`, which appends the exclusions.
  Removing `STARRED`/`SENT`/`DRAFT` raises `SafetyViolation`.
- **Only `[Superhuman]` labels can be deleted.** Any other name raises.
- **`batchModify` chunks at 1,000 ids**, tested at 999/1,000/1,001/2,500.
- **Operations over 5,000 messages** print their count, proceed, and are flagged
  in the final report.
- **Every write is logged** to `reports/oplog.<account>.jsonl` with the query, the
  count and every message id, which makes it reversible:
  ```bash
  .venv/bin/python -m gmail_rescue undo --account personal --op <op_id>
  ```

### The two human-mail guards

The stale-unread and read-backlog sweeps are broad enough to catch real
correspondence, so they run behind two guards derived from your own data — you
are never asked to classify a sender:

- **Correspondents** — every address you have written to in the last 12 months,
  read out of your SENT mail. If you have emailed them, their mail is not machine
  mail and it stays in the inbox.
- **VIP** — anything labelled `01_VIP` on the personal account.

### The Superhuman gate

Gmail filters survive an OAuth revocation. Before any labelling work, the tool
checks whether a `[Superhuman]` label has been applied to recent mail; if one
has, a leftover filter is still live and it stops rather than fighting it.
Removing those filters is the fix, and `cleanup` does it first, before anything
else.

---

## Configuration

`config/domains.json` holds the sender lists. Edit it and re-run `filters` to
change behaviour — for example moving `uber.com` out of `promotional` so ride
receipts stay in the inbox.

`config/filters.<account>.json` is the generated filter set, written on every
`filters` run and committed to git so it is versioned and re-runnable. Entries
tagged `"source": "derived"` were inferred from your own 90-day data: 5+ messages,
`List-Unsubscribe` on 80%+ of them, and never emailed by you. Each carries its
reasoning.

---

## Development

```bash
.venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m pytest tests/ -q
```

122 tests, no credentials required. `tests/fake_gmail.py` is an in-memory Gmail
double with a working query evaluator, so the end-to-end tests run all five
phases against a realistic mailbox and assert the safety invariants hold —
starred mail untouched, VIP untouched, correspondents untouched, message count
unchanged before and after.

**The live Gmail API is untested.** It cannot be exercised without your
credentials. The logic is verified against the double; the first real run is the
first time it touches Google's servers. That is what `preflight` is for.
