# The no-code path — fix both inboxes from your browser

Nothing to install. No Google Cloud project. No Python. You do this in Gmail on
your Mac, in about 45 minutes, and it works identically on both accounts because
you just sign into each one in turn.

**Nothing here deletes mail.** Archive removes a message from the inbox; it stays
in All Mail and stays searchable forever. The only Delete button in this document
is for *labels* and *filters*, and deleting either of those never deletes a
single message.

Do the personal account first — it is the buried one.

---

## Before you start: the one Gmail trick that makes this possible

When you run a search in Gmail and tick the checkbox at the top left, Gmail
selects the 50 messages on screen. A line then appears saying:

> All 50 conversations on this page are selected.
> **Select all conversations that match this search**

**Click that link.** Now you are acting on all 26,000, not 50. Every bulk step
below depends on it. If you do not see the link, the search matched fewer than
one page and you can just act on what is selected.

Gmail will warn you it is performing a bulk action. That is expected. Confirm it.

---

## Part 1 — Kill the Superhuman system (personal account only)

Superhuman's OAuth access is revoked, but **Gmail filters survive a revocation**.
If labels are still appearing, a leftover filter is doing it. Remove the filters
first, then the labels — in that order, or you will delete the evidence of which
filter was guilty.

### 1a. Delete the filters

1. Gmail → gear icon → **See all settings** → **Filters and Blocked Addresses**.
2. Look down the list for any filter whose action mentions a label starting with
   `[Superhuman]`.
3. Click **delete** on each one. Confirm.

### 1b. Delete the labels

1. Same settings screen → **Labels** tab.
2. Scroll to the `[Superhuman]` entries. There should be ten:
   `AI/Marketing`, `AI/Meeting`, `AI/Pitch`, `AI/News`, `AI/Waiting`, `Muted`,
   `AI/Social`, `AI/Respond`, `ru`, `AutoArchived`.
3. Click **remove** next to each. Confirm each one.

Deleting a label does not delete the mail that carried it. Those messages stay
exactly where they are; they simply stop being tagged.

---

## Part 2 — Empty the backlog (both accounts)

For each search below: paste it into the Gmail search box, press Enter, tick the
top-left checkbox, click **"Select all conversations that match this search"**,
then click the **Archive** button (the box-with-a-down-arrow icon).

Run them in this order. The `-is:starred` on every line is what protects
anything you have starred.

**1. Promotions older than two days**
```
in:inbox category:promotions older_than:2d -is:starred
```

**2. Updates older than two days**
```
in:inbox category:updates older_than:2d -is:starred
```

**3. All social**
```
in:inbox category:social -is:starred
```

**4. Stale unread — the long tail**
```
in:inbox is:unread older_than:30d -is:starred -label:01_VIP
```
Before archiving this one, **skim the sender column for anyone you actually
know**. This is the only search in the list that can catch real mail from a real
person. If you spot someone, star them and re-run the search — starring removes
them from the results. On the business account, drop the `-label:01_VIP` part.

**5. The read backlog — this is what actually unburies the inbox**
```
in:inbox is:read older_than:30d -is:starred -label:01_VIP
```
This is the big one: roughly 20,000 already-read messages sitting in your inbox
doing nothing. Archiving them takes the inbox down to about the last month.
Again, drop `-label:01_VIP` on business.

**6. Kill the phantom unread badge**
```
is:unread -in:inbox older_than:30d -is:starred
```
These are ~5,600 messages that are already archived but still counted as unread.
Do **not** archive these — they already are. Instead select all matching, then
click the **Mark as read** button (the open-envelope icon). Nothing moves; the
badge just stops lying to you.

---

## Part 3 — Build the labels (business account)

Settings → **Labels** → **Create new label**, once for each:

`Clients`, `Leads`, `Admin`, `Newsletters`

Then create `IS`, and create `Receipts 2026` with **"Nest label under"** set to
`IS`. That gives you `IS/Receipts 2026`.

Leave `To respond` and `Info Alias` alone — those two survived the wipe and are
not doing any harm.

On the personal account you already have `01_VIP`, `Newsletters`, `Finances`,
`Shopping`, `Health / Fitness` and `Personal/Entertainment`. Add one more label
called `IS`.

---

## Part 4 — The filters (this is the part that keeps it fixed)

Filters act on **new incoming mail**. They can also be applied to what is already
there — see the checkbox below, which does a lot of Part 2's work for you.

### How to make one (the mechanics, once)

1. Click the **sliders icon** at the right end of the Gmail search box
   ("Show search options").
2. Fill in the **From** field (or **To**, where the table says so). Paste the
   whole line exactly, `OR`s and all — Gmail understands it.
3. Click **Create filter** (bottom right of that panel).
4. On the next panel, tick the boxes the table lists.
5. **Also tick "Also apply filter to N matching conversations."** This is the one
   worth knowing about: it applies the filter to mail you already have, not just
   future mail. On the newsletter and promo filters it archives the backlog for
   you. On the label-only filters it back-labels everything historically.
6. Click **Create filter**.

If a label in the table does not exist yet, the "Apply the label" dropdown has a
**New label** option at the bottom — you can make it right there.

**Two boxes you should not tick, ever:** *Delete it* and *Forward it*.

### Personal account

| # | Field | Paste exactly | Tick these |
|---|---|---|---|
| 1 | From | `tldrnewsletter.com OR producthunt.com OR deeperlearning.producthunt.com OR morningbrew.com OR beehiiv.com OR substack.com OR forwardfuture.ai` | Skip the Inbox **+** Apply label `Newsletters` |
| 2 | From | `emails.whop.com OR popmenu.com OR e.lifetime.life OR postable.com OR wolfandshepherd.com` | Skip the Inbox **+** Mark as read |
| 3 | From | `chase.com OR americanexpress.com OR discover.com OR robinhood.com OR creditkarma.com OR e.tdbank.com` | Apply label `Finances` — **nothing else** |
| 4 | **To** | `james@intersectionstrategies.co` | Apply label `IS` — **nothing else** |

Filter 2 gets **Mark as read** because those never need reading and you do not
want them quietly rebuilding the unread pile you just cleared. Filter 1 does
*not* get it — you want to see how much is waiting when you open `Newsletters`.

Filters 3 and 4 deliberately have no Skip the Inbox. Bank alerts and anything to
your business address stay in front of you; the label is just so you can find
them later.

### Business account

| # | Field | Paste exactly | Tick these |
|---|---|---|---|
| 1 | From | `stripe.com OR squareup.com OR intuit.com OR paypal.com OR bill.com OR ramp.com OR brex.com OR expensify.com` | Apply label `IS/Receipts 2026` — **nothing else** |
| 2 | From | `vercel.com OR cloudflare.com OR namecheap.com OR godaddy.com` | Skip the Inbox **+** Apply label `Admin` |
| 3 | From | `github.com OR slack.com OR notion.so OR figma.com OR linear.app OR atlassian.com` | Apply label `Admin` — **nothing else** |
| 4 | From | `deeperlearning.producthunt.com OR producthunt.com OR m.learn.coursera.org OR tldrnewsletter.com OR substack.com OR beehiiv.com OR leftclick.ai` | Skip the Inbox **+** Apply label `Newsletters` |

Filters 2 and 3 look like they should be one filter and are deliberately not.
Vercel and your registrar only ever send you machine noise — deploy succeeded,
domain renews in 30 days — so that can leave the inbox. GitHub, Slack, Notion,
Figma and Linear send you mail **because a human did something**: commented on
your PR, mentioned you, assigned you a task. Those get the `Admin` label so they
are findable, but they stay in the inbox where you will see them.

---

### What I took out, and why

These four were in the earlier draft. Each one would have cost you mail you
actually want, so I removed them rather than leave you to find out.

- **`uber.com`** — sends your ride receipts down the same domain as its
  marketing. Skipping the inbox would archive the receipts. Gmail's own
  Promotions category already catches Uber marketing, and Part 2 sweeps that, so
  you lose nothing by leaving it off.
- **`sevenrooms.com`** — that is your restaurant **reservation confirmations**.
- **`livenation.com`** — that is your **event tickets**.
- **`google.com`** — this is the one that would have hurt. Google Calendar
  invitations, Google Docs share notifications and Drive share notices all come
  from `google.com`. A blanket skip-inbox rule on that domain means you stop
  seeing meeting invites. Left out entirely.

If you later want Workspace admin mail labelled, do it precisely: open one of
those emails, click the arrow next to the sender to see its exact address (it
will be something like `workspace-noreply@google.com`), and build a filter on
that full address rather than on `google.com`.

The rule behind all of it: **mail with a person behind it stays in the inbox
untouched. Machine mail gets a label. Only newsletters and promos skip the
inbox.** When you are unsure about a new sender, ask which of those three it is —
and if a domain sends both kinds, do not skip the inbox on it.

---

## Part 5 — Unsubscribing, whenever you feel like it

Do not make a project of this. Once the filters are in, nothing on this list is
interrupting you any more — it is all landing quietly in `Newsletters`. Unsubscribe
opportunistically instead:

Open `Newsletters` once a week. Anything you scroll past without opening two
weeks running, kill on the spot — Gmail puts an **Unsubscribe** link right next
to the sender's name at the top of the message. One click, done.

**The one thing worth knowing:** TLDR and Product Hunt send several different
editions from the same address (TLDR AI, TLDR Web Dev, TLDR Founders, and so on).
Unsubscribing from one does **not** stop the others — they are separate lists. So
if you want to keep TLDR AI but drop the rest, you have to open one of each
edition you don't read and unsubscribe from that one individually.

---

## The weekly habit

Once a week: clear the inbox (it is now people plus `Finances` plus `IS`), skim
`Newsletters` and select-all-archive the rest, glance at `01_VIP`. Fifteen
minutes. When something new starts interrupting you, add its domain to the
matching filter and it never does again.

---

## One loose end — clearbriefco@gmail.com

That account forwards mail into your personal one. The rule lives on *that*
account, so it cannot be seen or changed from either of the other two. It has
been dormant since late July.

You have decided to delete it. That has to be done from inside that account —
sign into `clearbriefco@gmail.com` and go to **myaccount.google.com** → **Data
& privacy**, then pick one:

- **Delete a Google service → Gmail.** Removes the mailbox and the address,
  leaves the underlying Google account intact for anything else attached to it.
- **Delete your Google Account.** Takes everything with it — Drive, Photos,
  purchases, and any third-party logins that use that address to sign in.

Both are permanent, and Google never re-issues a deleted Gmail address. Before
you do it, search that mailbox for anything still arriving: once it is gone,
mail sent there bounces instead of forwarding to you.

If all you actually want is the forwarding stopped, you do not have to delete
anything — Settings → **Forwarding and POP/IMAP** → disable forwarding does it,
and keeps the address parked in case something still depends on it.
