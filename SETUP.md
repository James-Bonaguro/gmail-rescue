# One-time setup — about ten minutes, once, ever

This registers a small program with Google so it is allowed to ask for access to
your Gmail. You do it once and never again.

**What you are creating is not a password.** At the end you get a file called
`credentials.json`. It is the program's ID badge — it identifies the app, it does
not grant access to anything. You still have to click "Allow" in your own browser
before the program can read a single message. And it only ever gets the two
permissions listed at the bottom of this page.

Do this on your Mac, in a normal browser window. Have both email addresses handy:

- `james.bonaguro@gmail.com` (personal)
- `james@intersectionstrategies.co` (business)

---

## Step 1 — Make a project

1. Go to **https://console.cloud.google.com**
2. Sign in as **james.bonaguro@gmail.com**.
3. At the top of the page there is a project dropdown (it may say "Select a
   project"). Click it, then click **New Project**.
4. Name it `gmail-rescue`. Leave everything else alone. Click **Create**.
5. Wait a few seconds, then make sure the dropdown at the top now says
   **gmail-rescue**. If it does not, click it and select the project.

> A "project" here is just a container. It costs nothing and it does nothing on
> its own.

---

## Step 2 — Switch on the Gmail API

1. In the search bar at the very top, type `Gmail API` and open the result.
2. Click the blue **Enable** button.
3. Wait for it to finish.

That tells Google "programs in this project are allowed to talk to Gmail."

---

## Step 3 — The consent screen

This is the screen *you* will see later when you click Allow.

1. Left sidebar → **APIs & Services** → **OAuth consent screen**.
   (On the newer console it may be under **Google Auth Platform** → **Branding**.)
2. Choose **External**. Click **Create**.
3. Fill in only the required fields:
   - **App name**: `gmail-rescue`
   - **User support email**: your gmail address
   - **Developer contact email**: your gmail address
4. **Save and Continue**.
5. On the **Scopes** screen, do nothing. **Save and Continue**.
6. On the **Test users** screen, click **+ Add Users** and add **both**
   addresses, one per line:
   ```
   james.bonaguro@gmail.com
   james@intersectionstrategies.co
   ```
   This step is the one people miss. If an address is not listed here, that
   account cannot sign in later.
7. **Save and Continue**, then **Back to Dashboard**.
8. Confirm the publishing status says **Testing**. Leave it there.

> **Testing mode needs no review from Google.** You will see an "unverified app"
> warning when you sign in. That is correct and expected — you are the developer
> and the only user. Click **Advanced**, then **Go to gmail-rescue (unsafe)**.
>
> The one cost of testing mode: sign-in tokens expire after seven days. If the
> tool ever says the token expired, re-run the `auth` command and click through
> again. It takes fifteen seconds.

---

## Step 4 — Create the credentials

1. Left sidebar → **APIs & Services** → **Credentials**.
2. Top of the page → **+ Create Credentials** → **OAuth client ID**.
3. **Application type**: **Desktop app**. This matters — it is what allows the
   browser sign-in to hand the approval back to the program on your own machine.
4. Name it `gmail-rescue-desktop`. Click **Create**.
5. A box appears with your client ID. Click **Download JSON**.
6. Rename the downloaded file to exactly **`credentials.json`** and move it into
   this repo's folder, next to `README.md`.

`credentials.json` and the whole `tokens/` folder are already in `.gitignore` —
they were put there in the very first commit, before any credential file could
exist. Nothing secret is ever pushed.

---

## Step 5 — Install and sign in

In Terminal, from this folder:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then sign in once per account:

```bash
.venv/bin/python -m gmail_rescue auth --account personal
.venv/bin/python -m gmail_rescue auth --account business
```

Each opens a browser window.

- The **first** command: sign in as `james.bonaguro@gmail.com`.
- The **second** command: sign in as `james@intersectionstrategies.co`.

If the browser is already signed into the wrong account, click **Use another
account**. Picking the wrong one here is the easiest mistake to make, so the tool
checks the address you actually authorised and tells you if it does not match
what you asked for.

Both times you will hit the "unverified app" warning. **Advanced** → **Go to
gmail-rescue (unsafe)**. Then **Continue** to grant the two permissions.

When it works you will see:

```
  Authorised: james.bonaguro@gmail.com
  Token saved to tokens/personal.json
```

That is Phase 0 done, permanently. Go to `README.md` for the runbook.

---

## What you actually granted

Two permissions, and no others:

| Scope | What it allows | What it does not allow |
|---|---|---|
| `gmail.modify` | Read mail, add and remove labels, archive | **Cannot permanently delete anything.** Google does not include deletion in this scope. |
| `gmail.settings.basic` | Read and create filters, read forwarding settings | Cannot change your password, recovery details, or account security |

The narrower scope is deliberate: even if this tool had a catastrophic bug, the
permission it holds does not include the ability to delete your mail.

To revoke either account at any time: **https://myaccount.google.com/permissions**
→ find `gmail-rescue` → **Remove access**. Deleting the matching file in
`tokens/` does the same thing locally.
