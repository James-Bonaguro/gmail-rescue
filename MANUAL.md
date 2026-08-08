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

Filters only act on **new incoming mail**. They do nothing to the backlog, which
is why Part 2 came first.

For each one: Gmail search box → click the **sliders icon** on the right of the
box (Show search options) → fill in the **From** field → **Create filter** →
tick the boxes listed → **Create filter**.

### Personal account

| # | From field (paste exactly) | Tick these boxes |
|---|---|---|
| 1 | `tldrnewsletter.com OR deeperlearning.producthunt.com OR producthunt.com OR morningbrew.com OR mail.beehiiv.com OR substack.com OR forwardfuture.ai` | Skip the Inbox **+** Apply label: `Newsletters` |
| 2 | `emails.whop.com OR popmenu.com OR uber.com OR e.lifetime.life OR postable.com OR wolfandshepherd.com OR sevenrooms.com OR livenation.com` | Skip the Inbox |
| 3 | `chase.com OR americanexpress.com OR discover.com OR robinhood.com OR creditkarma.com OR e.tdbank.com` | Apply label: `Finances` — **do not** tick Skip the Inbox |
| 4 | leave From blank, put `james@intersectionstrategies.co` in the **To** field | Apply label: `IS` — **do not** tick Skip the Inbox |

On filter 2, note that `uber.com` also carries your ride receipts. If you want
those in the inbox, take `uber.com` out of that list.

### Business account

| # | From field (paste exactly) | Tick these boxes |
|---|---|---|
| 1 | `stripe.com OR squareup.com OR intuit.com OR paypal.com OR bill.com OR ramp.com OR brex.com OR expensify.com` | Apply label: `IS/Receipts 2026` — **do not** tick Skip the Inbox |
| 2 | `google.com OR github.com OR vercel.com OR cloudflare.com OR namecheap.com OR godaddy.com OR notion.so OR slack.com OR linear.app OR figma.com` | Skip the Inbox **+** Apply label: `Admin` |
| 3 | `deeperlearning.producthunt.com OR producthunt.com OR m.learn.coursera.org OR tldrnewsletter.com OR substack.com OR mail.beehiiv.com` | Skip the Inbox **+** Apply label: `Newsletters` |

The rule behind all of these: **mail with a person behind it stays in the inbox
untouched. Machine mail gets a label. Only newsletters and promos skip the
inbox.** If you ever wonder whether to add a sender, ask which of those three it
is.

---

## Part 5 — Unsubscribing

The scripted path produces a ranked list of your top 25 offenders with their
unsubscribe links extracted. Doing it by hand, the equivalent is:

1. Search `in:inbox OR in:anywhere newer_than:90d` and sort by sender in your
   head — or simpler, just work the `Newsletters` label for a week.
2. Gmail shows an **Unsubscribe** link next to the sender name on most bulk mail.
   Click it there; it is the same one-click mechanism.
3. For TLDR and Product Hunt specifically: they send several different editions
   from the same domain, each with its own unsubscribe link. Unsubscribing from
   one does **not** stop the others. Open one edition you do not read, unsubscribe
   from that one, and repeat per edition.

---

## The weekly habit

Once a week: clear the inbox (it is now people plus `Finances` plus `IS`), skim
`Newsletters` and select-all-archive the rest, glance at `01_VIP`. Fifteen
minutes. When something new starts interrupting you, add its domain to the
matching filter and it never does again.

---

## One loose end

`clearbriefco@gmail.com` forwards mail into your personal account. That rule
lives on *that* account — it cannot be seen or changed from the other two. It has
been dormant since late July. If you want it off, sign into that account and turn
it off in its own Settings → Forwarding.
