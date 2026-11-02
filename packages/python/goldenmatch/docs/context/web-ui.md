# Web UI (`goldenmatch[web]`)

The optional review/inspection UI: what ships, how it is served, and what is deferred.

> Reference detail extracted from `packages/python/goldenmatch/CLAUDE.md` so it
> is read when relevant rather than loaded into every session. The Tier-1 rule
> that always applies stays in that file, which links here.

## Web UI (`goldenmatch[web]`)

- **Source/output split:** frontend source lives **outside** the python package at `packages/python/goldenmatch/web/frontend/`; build output lands **inside** the package at `goldenmatch/web/static/`. Don't collapse the two — wheel inclusion via `[tool.hatch.build.targets.wheel.force-include]` and dev-tooling separation both depend on this split.
- **`goldenmatch/web/static/.gitkeep` is intentional.** Real assets are gitignored (root `.gitignore` carve-out); the placeholder stays so source checkouts have the dir present and the wheel `force-include` glob has something to match.
- **Wheel build sequence:** `python scripts/build_web.py && hatch build`. The script invokes `pnpm install --frozen-lockfile && pnpm build` in `web/frontend/`, then mirrors `dist/` into `goldenmatch/web/static/`. Promoting to a hatch custom build hook is a deliberate v2 follow-up.
- **`[web]` extra is truly optional.** `cli/serve_ui.py` does its `from goldenmatch.web.app import create_app` import lazily (inside the command body) so users on plain `pip install goldenmatch` still get a working CLI. Test guards: `tests/web/test_optional_extra.py`.
- **`AppState.rules` is a typed `RulesPayload | None`** (not `dict | None`) — preview consumes the typed object without re-validating per request. `goldenmatch/web/rules.py::load_rules_from_yaml` is the single source of the 0.85 default threshold; don't re-default in the router.
- **Save path is atomic.** `routers/rules.py::save_rules` writes to `goldenmatch.yml.tmp`, then `os.replace`s. The `.yml.bak` is captured BEFORE the rewrite. Both spellings (`matchkey` singular, `matchkeys` plural) are popped before writing the canonical singular key — without that, files that previously held the plural key end up with both side-by-side.
- **Preview = per-dataset bounded LRU.** `goldenmatch/web/registry.py::PreviewRegistry` (default `max_entries=8`) owns temporary lineage/clusters/source and preview-local labels. Each `POST /preview` creates a fresh run name; the same run endpoints serve saved and temporary runs. Preview row IDs are positional in the sample, so their labels must never be used as full-dataset corrections.
- **Preview rejects `embedding`/`record_embedding` scorers** at the router with a 400 — they need model bootstrap (HF download / Vertex creds) the local server doesn't wire up. UI dropdown selection of those would otherwise produce a 30s timeout.
- **Preview pre-validates matchkey columns** against `data.csv.columns` and raises `ValueError` (→ 400) on a typo. The engine itself accepts unknown columns silently and returns empty results, which reads as "no matches" rather than an error in the UI.
- **`SCORERS` / `TRANSFORMS` const arrays in `web/frontend/src/lib/types.ts` mirror `goldenmatch/config/schemas.py::VALID_SCORERS` / `VALID_SIMPLE_TRANSFORMS`.** Update both when adding scorers — the workbench dropdowns won't surface new ones otherwise.
- **Pair canonicalization for labels.** `web/labels.py::_canonical_pair` matches the project-wide `(min, max)` invariant. Without it, labeling pair (0,1) then relabeling pair (1,0) — which the inspector may surface either way — would split into two phantom dedup-table entries.
- **Label scope is explicit.** Saved full-data runs share the selected dataset's `labels.jsonl` and mirror steward decisions into its Learning Memory. Pass `run_name` on writes. Preview labels live with that preview and are not mirrored. Requests without a run retain dataset-local labels but do not mirror them. The CLI ground-truth CSV remains a separate format.
- **Frontend stack is bleeding-edge** as create-vite scaffolded: Vite ^8, React ^19.2, TypeScript ^6, ESLint ^10. Build's clean today but a major upgrade in any of these may need test/config touches. TanStack Router v1 / Query v5 / Table v8 are all stable.
- **Single-tenant by design** — no concurrency guard on `state.rules`, `state.registry`, the YAML file, or `labels.jsonl`. Localhost dev tool; revisit if/when this surface ever grows past one user.
- **`python -m goldenmatch.cli.main serve-ui` shadows worktree code.** Resolves the installed `goldenmatch` from site-packages, not the worktree source — testing web changes against the installed package will pass, then CI / the next user fails. Either `pip install -e packages/python/goldenmatch[web]` first, or run via a small wrapper that constructs `AppState` + `uvicorn.run(app, ...)` directly with `sys.path` prepended to the worktree.
- **SPA fallback (Wave 1.2, 2026-06-05): SHIPPED.** `web/app.py::SPAStaticFiles` subclasses `StaticFiles` and falls back to `index.html` on a 404, so a hard refresh / shared URL on `/workbench`, `/runs/<name>`, etc. now serves the shell and client-routes. Real assets still resolve normally; API routes are registered before the mount so they win.
- **Web/REST/A2A auth + health.** Public-interface binds require their respective tokens: `GOLDENMATCH_WEB_TOKEN`, `GOLDENMATCH_API_TOKEN`, and `GOLDENMATCH_AGENT_TOKEN`. Web auth covers `/api/v1/*` except `/api/v1/healthz`; the page shell stays public. Web readiness requires an existing workspace plus legacy `data.csv` or a published imported snapshot. The Docker liveness probe uses the shell so an empty workspace can open its first import. REST `/health` and A2A `/health` remain their own readiness interfaces.
- **Demo project at `web/demo/`** is checked in: 28-contact `data.csv`, 7-row `reference.csv` (for `/match`), 2 saved runs, `labels.jsonl`, `goldenmatch.yml`. Use it for screenshots, walkthrough videos, and the `examples/python/07_web_ui_walkthrough.py` script. Runtime artifacts the demo accumulates (preview run files, `.goldenmatch/memory.db`) are gitignored — `git checkout -- web/demo/labels.jsonl` to revert label additions if you've been clicking around.
- **Deferred for v2** (the design doc that listed these has since been deleted):
  1. Cluster force-graph view.
  2. Multi-run diff (A vs B).
  4. Multi-user accounts and authorization.
  5. Persisting workbench previews to disk.
  6. Async preview job + streaming progress (current ceiling: 30s synchronous).

## Dataset imports and remote sources

- `web/datasets.py` owns snapshot publication, validation, resource limits, upload
  staging/expiry, and request-scoped selection via `X-Goldenmatch-Dataset`.
  Imported data lives at `<workspace>/.goldenmatch/datasets/<id>/data.csv`; the
  manifest records immutable name/source/columns/row count. Legacy requests reuse
  the original AppState and its existing artifacts.
- `web/connections.py` owns PostgreSQL connection profiles and read-only table
  snapshots. Passwords are Fernet-encrypted in `<workspace>/.goldenmatch/connections.json`;
  the encryption key exists only in `GOLDENMATCH_CONNECTION_KEY`. Import uses a
  server cursor with bounded batches and statement/connect timeouts, never the
  general connector's all-rows `read()` or write operations.
- CSV and XLSX imports stream validated rows directly into an atomically
  published snapshot. Multipart ingress is size-limited at the ASGI receive
  seam, without consuming and replaying the request in BaseHTTPMiddleware.
  Workbook expanded ZIP size, rows, columns, cells, preview bytes, and normalized
  output bytes are independently bounded. A shared import slot rejects
  competing imports with 429.
- The browser captures dataset selection for its document lifetime. A switch
  persists the new ID, clears query caches, and reloads; another browser tab
  cannot change the scope of currently rendered rows. Auth remains in memory,
  so activation requires signing in again.
- Install `goldenmatch[web,polars,web-data]` for this full WebUI. `openpyxl` is
  already a core dependency; `web-data` adds cryptography and psycopg, not the
  optional document extraction/ML dependencies.
- See the root README's Coolify section for secrets, TLS, explicit private-host
  approval, limit environment variables, persistent storage, and backups.
