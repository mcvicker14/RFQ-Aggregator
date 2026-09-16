# Deployment Guide — Render

This walks through putting Principal Opportunity Intelligence on the public internet,
on a real URL you can open in any browser, using [Render](https://render.com).

## Why Render

The application has three moving parts that all need to run somewhere: a database, a
backend, and a frontend. Render can host all three from one account, deploys directly
from this GitHub repository (no separate upload step), gives every service a working
HTTPS address automatically, and its free tier requires no credit card — a good fit
for getting this in front of a real browser to test, which is the immediate goal.
Section **Free tier limitations** below is honest about what the free tier does *not*
give you, so there are no surprises.

This repo includes a `render.yaml` file at its root — a "Blueprint" that tells Render
about all three pieces (database, backend, frontend) at once, so most of the setup is
one click rather than three separate manual setups.

## What you'll need to do (there's no way around a few manual steps)

Claude cannot create an account on your behalf — that requires your own email and
agreement to Render's terms. Everything below is normal web-browser clicking, nothing
technical, and each step says exactly what to click.

### Step 1 — Create a Render account

1. Go to [dashboard.render.com/register](https://dashboard.render.com/register).
2. Sign up (using "Sign in with GitHub" is easiest, since Render needs GitHub access
   anyway — click **GitHub**, then approve the request).
3. No credit card is required for this.

### Step 2 — Give Render access to this one repository

1. If you signed up with GitHub, Render will ask which repositories it can see.
   Choose **Only select repositories** and pick `mcvicker14/RFQ-Aggregator`
   (don't grant it access to anything else).
2. If you signed up another way, go to **Account Settings → GitHub** in Render and
   connect it there instead.

### Step 3 — Deploy the Blueprint

1. In the Render dashboard, click **New +** (top right) → **Blueprint**.
2. Select the `RFQ-Aggregator` repository.
3. Branch: choose `claude/principal-opportunity-intelligence-jwitkf`.
4. Render will read `render.yaml` and show you three things it's about to create:
   a database (`principal-oi-db`), a backend web service (`principal-oi-api`), and a
   frontend web service (`principal-oi-web`).
5. Render will show a form for values it can't fill in itself. Fill in what you can
   now (leave the rest — you can always come back):
   - **ADMIN_INITIAL_EMAIL** — the email you want to log in with.
   - **ADMIN_INITIAL_NAME** — your name.
   - **ADMIN_INITIAL_PASSWORD** — a password you make up right now. This becomes your
     real login. Nobody but you will see it — not Claude, not GitHub.
   - **SAM_GOV_API_KEY** / **ANTHROPIC_API_KEY** — leave these blank for now. The app
     works fully without them; it just won't sync from SAM.gov or read documents with
     AI until they're added later (see the root `README.md` for how to get them).
   - **FRONTEND_ORIGIN** and **BACKEND_URL** — leave these blank. You'll fill them in
     during Step 5, once Render has assigned the actual addresses.
6. Click **Apply** / **Create**. Render will start building both services. This
   typically takes several minutes the first time.

### Step 4 — Wait for both services to say "Live"

You'll land on a dashboard showing both services building. Each one goes through
"Building" → "Deploying" → "Live" (or "Deploy failed", covered below). Wait for both
`principal-oi-api` and `principal-oi-web` to say **Live**.

If either says **Deploy failed**: click into it, open the **Logs** tab, copy
whatever's shown near the bottom, and send it to Claude — that's enough to diagnose
and fix.

### Step 5 — Connect the frontend to the backend (required)

The two services need to know each other's address. Render assigns these
automatically, but the blueprint can't know them in advance, so this one connection
has to be made by hand:

1. Click into the **principal-oi-api** service. Near the top of the page is its URL —
   it looks like `https://principal-oi-api-xxxx.onrender.com`. Copy it.
2. Click into the **principal-oi-web** service → **Environment** tab.
3. Find **BACKEND_URL**, paste the URL you copied as its value, click **Save
   Changes**. This triggers a short redeploy of the frontend only.
4. While you're at it: click into **principal-oi-web**, copy *its* URL the same way,
   go back to **principal-oi-api → Environment**, paste it as **FRONTEND_ORIGIN**,
   and save. This step is optional (see `render.yaml`'s comment on it) but tidy to do
   now.

### Step 6 — Open the app

Once `principal-oi-web` finishes redeploying, open its URL in a browser. That's the
address for using Principal Opportunity Intelligence going forward — see **Bookmark
this** below.

## Free tier limitations (read before relying on this)

- **The free database expires 30 days after creation**, with a 14-day grace period
  to upgrade before Render deletes it. Fine for testing now; before that window
  closes, either upgrade the database to a paid plan (a few dollars a month) in the
  Render dashboard, or ask Claude to walk you through it when the time comes.
- **Free web services fall asleep after 15 minutes of no traffic** and take about a
  minute to wake back up on the next visit. You'll notice this as a slow first load
  after a break — that's expected, not a bug.
- **Uploaded documents don't survive a redeploy.** The app currently stores uploaded
  files on the service's local disk, which Render resets on every deploy. This is a
  known, documented limitation (see `docs/ROADMAP.md`) — fine for testing the
  workflow, not yet suitable for documents you need to keep. Moving this to durable
  storage (S3 or Render's paid Persistent Disks) is future work, not done here per
  your instruction not to add features during this deployment.

None of this blocks testing the application today — it just means the free tier is a
testing environment, not a permanent home, until you decide to upgrade it.

## Bookmark this

Once deployed, `principal-oi-web`'s `.onrender.com` address is what you'll use every
time — bookmark it. Per your instruction, no custom domain is connected yet; that's a
later step once you've confirmed everything works the way you want on this URL.
