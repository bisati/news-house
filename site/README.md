# News House site bundle

This folder is what deploys to Vercel (on the `site` branch, alongside the rendered `*.html` pages and `fonts/`): `vercel.json` routes `/feedback` to the `api/feedback.py` serverless function, which validates taps posted by the page and inserts them into the Neon `feedback_inbox` table using the `NEON_DATABASE_URL` environment variable set in Vercel's project settings; the Mac later syncs and clears that inbox. The function is self-contained and imports nothing from `newshouse`.

`vercel.json` also carries an `ignoreCommand` that skips the build for any branch but `site`; the repo root has a `vercel.json` with the same command, so a push to `main` never deploys.
