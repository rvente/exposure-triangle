# Deployment guide — Cloudflare Pages

This repo deploys as a static site to Cloudflare Pages. The Flask app
is exported through `freeze.py` into `_static_build/`, and that
directory is uploaded as a Pages deployment. No server runs in
production — `LocalBackend` mirrors the reducer in JS and persists
state to `localStorage`.

## Prerequisites

- **Cloudflare account** with Pages enabled.
- **wrangler** auth — either log in interactively or set an API token:
  ```bash
  npx wrangler login                 # opens a browser for OAuth
  # or
  export CLOUDFLARE_API_TOKEN=<token>
  ```
  Verify with `npx wrangler whoami`.
- **Node** for `npx wrangler`. The `wrangler` CLI itself does not need
  a global install — `npx -y wrangler@latest` pulls a fresh copy.
- **Python 3.12** + `uv` to run `freeze.py`. Newer Python versions are
  blocked by `greenlet` (a Playwright transitive dependency in the
  dev group) failing to compile against 3.13 internals; pin 3.12 with
  `uv sync --python 3.12`.

## Build

From the repo root:

```bash
make freeze
# equivalent to:
# uv run python freeze.py
```

This produces `_static_build/` with every public route rendered to
disk:

```
_static_build/
├── index.html          (/)
├── intro/index.html    (/intro)
├── learn/{1..7}/index.html
├── quiz/{1..10}/index.html   (1–8 main + 9–10 bonus)
├── result/index.html
├── reference/index.html
└── static/{css,js,renders,icons}/
```

Total size is ~21 MB, well under the Cloudflare Pages 25 MB
project limit.

API routes (`/api/state`, `/api/event`, `/api/reset`) are deliberately
**not** frozen — they don't make sense without a server. `LocalBackend`
intercepts those actions client-side.

## Deploy

The Pages project is named **`exposure-triangle`**, served at
`exposure-triangle.pages.dev`. To deploy the current build:

```bash
npx -y wrangler@latest pages deploy _static_build \
  --project-name=exposure-triangle \
  --branch=main \
  --commit-dirty=true
```

- `--branch=main` ⇒ the upload becomes a production deployment.
  Omitting it (or using any other branch name) creates a preview-only
  deployment at a hash-prefixed subdomain.
- `--commit-dirty=true` is required when the working tree has
  uncommitted changes — wrangler refuses to mark a deploy as
  reproducible otherwise. Drop the flag once the tree is clean.

Successful output ends with two URLs:

```
✨ Deployment complete! Take a peek over at https://<hash>.exposure-triangle.pages.dev
```

The hashed URL is the immutable preview for that exact build. Production
(`https://exposure-triangle.pages.dev`) is updated within a few seconds.

## First-time project creation

If the `exposure-triangle` project does not yet exist on the account:

```bash
npx wrangler pages project create exposure-triangle \
  --production-branch=main
```

Then run the deploy command above.

## Verification

Smoke-test the live deployment after every push:

```bash
for path in / /intro/ /learn/1/ /quiz/1/ /quiz/9/ /result/ /reference/; do
  printf "%-15s " "$path"
  curl -s -o /dev/null -w "HTTP %{http_code}\n" \
    "https://exposure-triangle.pages.dev$path"
done
```

All routes should return `200`. `/quiz/9/` exists as a static page
because `LocalBackend` enforces the bonus gate client-side; direct URL
access still loads the page but redirects via the gate logic if the
learner hasn't earned the unlock.

For the per-question review on `/result/`, walk the flow in a browser
(quizzes record state in `localStorage`) and confirm each row shows the
prompt, the chosen option, the correct option (when wrong), and the
"Why:" rationale.

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `wrangler pages project list` returns 401 | Token missing or expired | `npx wrangler login` or refresh `CLOUDFLARE_API_TOKEN` |
| `greenlet` fails to compile during `uv sync` | Python 3.13+ broke an internal API used by `greenlet 3.0.x` | `rm -rf .venv && uv sync --python 3.12` |
| Deploy succeeds but production still serves old content | CF edge cache | Wait 30 s; force-reload (`Cmd-Shift-R`); add `?cache-bust=$(date +%s)` to test |
| `MissingURLGeneratorWarning` from `freeze.py` | Harmless — Frozen-Flask reports endpoints with no URL generator (e.g. `/api/*`); they're skipped on purpose | Ignore |
| Project size warning during deploy | Build over 25 MB | Trim renders under `static/renders/` (drop `.png` companions, keep `.avif`) |

## Custom domain

If pointing a custom domain at the project, configure it through the
Cloudflare Pages dashboard → project → Custom domains. Wrangler does
not currently set up CNAMEs from the CLI.
