# Working with Claude Code — running notes

Personal notes, not about this project. Parked here until they get a proper home.

## Move this somewhere it loads automatically

Claude Code starts every session cold. It does not remember the last one. That is
why this file exists at all — it is the memory.

Two files get read automatically at the start of every session:

- **`~/.claude/CLAUDE.md`** — loads in *every* session on this machine, whatever
  project you're in. This is where these notes belong.
- **`./CLAUDE.md`** — loads only in the repo it sits in. For project-specific
  facts ("tests run with `.venv/bin/pytest`", "never touch the vendor dir").

Until this moves into `~/.claude/CLAUDE.md`, it does nothing on its own — you'd
have to paste it in. Once it's there, the pattern compounds by itself.

---

## The ritual

At the end of a session, ask:

> How did I handle this session? Be direct — I want to get better at working with
> you, not be told I did fine.

Then add anything worth keeping to this file. That's the whole loop.

---

## What works (from the gmail-rescue session, Aug 2026)

**Write the brief with hard rules, real numbers, and a definition of done.**
The opening brief on that session had exact thread counts pulled from the API,
explicit "never do X" rules, and a checkable finish line. That's why the plan
landed in one pass instead of five rounds of clarification. Precision in the ask
buys back far more time than it costs.

**Say "I'm confused" the moment you feel it, in plain words.**
Mid-session: *"what does this mean, what cloud project, what script, sorry I am
genuinely confused."* That single message was the highest-leverage thing in the
whole session. Unspoken unease turns into a wasted afternoon three steps later.
There is no cost to asking and a large cost to not.

**Hand back decisions you don't have context to make.**
*"You make the calls."* When a tradeoff needs knowledge you don't have, delegating
it explicitly beats guessing at an answer. Safe to do once the guardrails are
already agreed — on that session the safety rules and tests were locked in first,
so delegating the rest was low-risk.

**Kill sunk cost out loud.**
*"Forget the cloud, I'll do it manual."* Time was already spent building the
scripted path when it became clear its main benefit wasn't wanted. Cutting it
immediately was correct. The work already done is not an argument for continuing.

**Point verification at the risky part, not at everything.**
*"Let's make sure Part 4 is done correctly."* Not "check it all" — a specific
finger on the one component that would run unsupervised from then on. That found
four filters that would have silently archived calendar invites, ride receipts,
restaurant reservations and event tickets. Broad "please review" would likely
have missed them.

---

## What to adjust

**Check the altitude before approving a plan, not during execution.**
The gmail-rescue brief was written in fairly technical terms — OAuth scopes,
Desktop app clients, batch operations. The plan got approved, and only once
execution started did it become clear that the infrastructure vocabulary didn't
match hands-on familiarity with it. That mismatch caused a real detour.

The fix is one question, asked *before* approving:

> Before I approve this — walk me through what I'll actually have to do myself,
> step by step, in plain English. Assume I've never used [the thing].

If the answer involves setup that sounds unappealing, that's the moment to ask
whether there's a route that skips it. On this session, the answer was yes, and
the manual route reached the same end state.

**Alarming tool output is usually just terse tooling.**
An early red `fatal:` message read as "GitHub is broken" for most of the session.
It was git saying the repo had no commits yet — which was true and fine. Worth
asking rather than absorbing:

> That output looked alarming — is it actually a problem?

---

## Lines worth reusing

```
Before I approve this — walk me through what I'll actually have to do myself,
step by step, in plain English. Assume I've never used [X].

Is there a version of this that doesn't require [setup I don't want to do]?

You make the calls on anything I don't have the context to decide.

What's the riskiest part of this, and how do we verify it specifically?

That output looked alarming — is it actually a problem?

How did I handle this session? Be direct.
```

---

## Standing preferences

- Plain English over jargon. Define a term the first time it appears.
- Say what *can't* be done and why, early — don't discover it three steps in.
- Don't claim something is done when it isn't. "The tool is built but your
  mailbox is untouched" is the useful sentence.
- Flag judgement calls that were made on my behalf, so I can reverse them.
