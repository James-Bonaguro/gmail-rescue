# gmail-rescue

Cleaning up and keeping clean two Gmail accounts:

- **Personal** — `james.bonaguro@gmail.com`
- **Business** — `james@intersectionstrategies.co`

## Start here → [MANUAL.md](MANUAL.md)

That's the route: click-by-click in your browser, nothing to install, about
45 minutes. It covers tearing out the Superhuman labels and filters, emptying the
backlog, building the labels, and installing the filters that stop it coming
back.

Everything below is what you need *after* that, when new mail starts showing up
that none of the existing filters know about.

**Nothing in this repo deletes mail.** Archiving removes a message from the inbox;
it stays in All Mail and stays searchable forever.

---

# Handling new senders

You will keep subscribing to things. New tools will start emailing you. This is
the whole maintenance workflow, and it takes about a minute per sender.

## The one question

When something new starts showing up in your inbox more than once, ask:

> **Is there a person behind this email?**

- **Yes** — a reply, a comment, an invite, someone mentioning you. **Leave it
  alone.** It belongs in the inbox. At most, give it a label so you can find it
  later — but never Skip the Inbox.
- **No** — a newsletter, a receipt, a deploy notice, a sale. It gets a filter.

Everything below is just working out which filter.

## What to do, by type

| What arrived | Action | Skip the Inbox? |
|---|---|---|
| Reply from a client, friend, anyone real | nothing at all | no |
| A new client — their whole domain | label `Clients` | **no** |
| Newsletter you actually want to read | label `Newsletters` | yes |
| Newsletter you don't want | **unsubscribe instead** — don't filter it | — |
| Store / retail marketing | no label needed, + Mark as read | yes |
| Receipt, invoice, payment confirmation | label `IS/Receipts 2026` (business) or `Finances` (personal) | **no** |
| Bank or credit card alert | label `Finances` | **no** |
| SaaS billing, renewal, deploy, usage alert | label `Admin` | yes |
| SaaS "someone commented / mentioned / assigned you" | label `Admin` | **no** — a person triggered it |
| Security alert, password reset, 2FA code | **leave it completely alone** | never filter these |

That last row matters. Never build a filter that touches security mail. If a rule
ever hides a login alert you needed to see, that is a bad day.

## Adding one — the fast way

1. Open one of the offending emails.
2. Click the **⋮** (three dots) at the top right **of the message**, not the page.
3. Choose **Filter messages like these**. Gmail pre-fills the sender for you.
4. Click **Create filter**, tick the actions from the table above, **Create
   filter**.

If it's something you already have a rule for — another newsletter, another
store — do this instead, so you don't end up with ninety filters:

## Adding to an existing filter (do this most of the time)

1. Gear → **See all settings** → **Filters and Blocked Addresses**.
2. Find the relevant filter (the newsletter one, the promo one) → **edit**.
3. In the **From** field, go to the end and type ` OR newdomain.com`.
4. **Continue** → **re-tick the boxes** — Gmail clears them on edit, which is the
   easy mistake here — → **Update filter**.
5. Tick **"Also apply filter to N matching conversations"** if you want it to
   clear what's already sitting there.

Four filters that each know about fifteen domains beats sixty filters. Gmail's
limit is 1,000, but yours is patience.

## Picking the right domain

Look at the actual sender address — click the arrow next to the sender name to
see it in full.

- **Pure newsletter companies** — use the bare domain. `substack.com` catches
  `mail.substack.com` and every publication under it, because Gmail's `from:`
  matches subdomains too.
- **Companies that send you both marketing and real mail** — use the *marketing
  subdomain only*. `e.lifetime.life`, `emails.whop.com`,
  `deeperlearning.producthunt.com`. Filtering the bare `lifetime.life` would
  catch your membership and billing mail along with the promos.

## The trap worth remembering

**Before you tick Skip the Inbox, ask: does this domain ever send me something
I'd be annoyed to miss?**

Four senders were caught by that question when these filters were built, and all
four are deliberately absent from every skip-inbox rule:

| Domain | Also sends |
|---|---|
| `google.com` | Calendar invitations, Docs comments, Drive shares |
| `uber.com` | ride receipts |
| `sevenrooms.com` | restaurant reservation confirmations |
| `livenation.com` | event tickets |

A domain that mixes marketing with things you need gets **labelled, not
archived** — or left alone entirely and handled by Gmail's own Promotions
category, which the backlog sweep already clears.

## Filter, or unsubscribe?

- **Unsubscribe** when you don't want it at all. One less rule to maintain, and
  it stops at the source.
- **Filter** when you want to keep receiving it but not be interrupted — the
  newsletters you genuinely skim, receipts, account notices.

Don't filter something you could just unsubscribe from.

---

# When something goes wrong

**"I think a filter ate something."** Search `in:anywhere from:whoever` — nothing
was deleted, so it is definitely still there. `in:anywhere` includes Spam and
Trash too.

**"This filter is too aggressive."** Settings → Filters and Blocked Addresses →
**edit** or **delete** it. Deleting a filter doesn't un-archive the mail it
already acted on; to bring that back, search for it, select all, and click **Move
to Inbox**.

**"My inbox is filling up again."** Something new is getting through. Sort by what
you're seeing most of, and add it to the matching filter — that's the loop, and
it should be a minute or two a month.

**Once a quarter**, glance at Settings → Filters and delete any rule for a service
you no longer use.

---

# The weekly habit

Clear the inbox — after the filters it's people, plus `Finances`, plus `IS`.
Open `Newsletters`, skim, select-all-archive the rest without guilt. Glance at
`01_VIP`. About fifteen minutes.

Business is the same loop with `Clients`, `Leads` and `Admin`, plus
`IS/Receipts 2026` at month end when you reconcile.

---

# The scripts (optional, ignorable)

There's a Python CLI in `gmail_rescue/` that does all of the above automatically
across both accounts, plus a ranked list of your worst senders with unsubscribe
links extracted. It needs a one-time Google Cloud registration
([SETUP.md](SETUP.md), ~10 minutes) and has to run on your own machine, because
Google requires you to click Allow in your own browser.

You decided against it and that's a reasonable call — its main advantage was the
sender analysis. It's here if you ever change your mind:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m gmail_rescue auth      --account personal
.venv/bin/python -m gmail_rescue diagnose  --account personal   # read-only
.venv/bin/python -m gmail_rescue preflight --account personal   # counts, no writes
.venv/bin/python -m gmail_rescue cleanup   --account personal
.venv/bin/python -m gmail_rescue filters   --account personal
.venv/bin/python -m gmail_rescue report
```

`config/domains.json` holds the same sender lists that `MANUAL.md` uses — a test
enforces that the two stay identical, so the doc can't drift from the code.

## Safety

Enforced in code and covered by tests, not left to good intentions:

- **No delete, trash or batchDelete call exists anywhere in the package.** A test
  parses the syntax tree of every source file to prove it, and a second test
  proves that checker actually catches a known-bad file rather than passing
  because it found nothing.
- Every bulk query gets `-is:starred -in:sent -in:drafts -in:chats -in:spam
  -in:trash` welded on before it runs.
- Only `[Superhuman]`-prefixed labels can be deleted; any other name raises.
- No skip-inbox filter can match a transactional domain — enforced by test.
- Every write is logged with its message ids, so `undo --op <id>` can reverse it.
- The OAuth scope requested (`gmail.modify`) cannot permanently delete mail, so
  Google blocks deletion independently of this code.

```bash
.venv/bin/python -m pytest tests/ -q     # 133 passed, no credentials needed
```

`tests/fake_gmail.py` is an in-memory Gmail with a working query evaluator, so
all five phases run against a realistic mailbox offline. The live API is untested
until it runs against a real account — which is what `preflight` is for.

## Loose end

`clearbriefco@gmail.com` forwards into the personal account and is marked for
deletion. That rule lives on that account and can't be reached from either of the
other two — see the end of [MANUAL.md](MANUAL.md) for how to remove it.
