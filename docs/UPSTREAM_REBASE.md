# Upstream Rebase Procedure (l-v-b fork)

The personal fork at `l-v-b/mcp-context-forge` tracks IBM upstream main on `origin`. Our patches live on `fork/main`. This document is the canonical runbook for syncing the fork to upstream — monthly on the 1st, or ad-hoc before any source patch.

## When

- **Monthly**, on the 1st (or first weekday after).
- **Before any new fork PR** that touches `gateway_service.py`, `db.py`, or `alembic/versions/`.
- **Any time the container restart-loops with `Multiple head revisions`** after a pull.

## Remotes (recap)

```
$ git remote -v
fork    git@github.com:l-v-b/mcp-context-forge.git (fetch / push)
origin  git@github.com:IBM/mcp-context-forge.git (fetch / push)
```

`origin → IBM` so `git pull origin main` Just Works for upstream syncs.

## Procedure

### 1. Pre-flight: stash personal experiments

Working tree on nixliam usually carries uncommitted personal customisations. Stash before any checkout:

```bash
cd ~/personal/github/mcp-context-forge
git stash push -m "pre-rebase-$(date +%Y-%m-%d)"
```

If there's nothing to stash, `git stash push` exits cleanly. Restore later with `git stash pop`.

### 2. Sync main from IBM, push to fork

```bash
git checkout main
git pull origin main --ff-only        # fast-forward; refuses on divergence
git push fork main                     # mirror to l-v-b
```

If `--ff-only` rejects (e.g. fork has commits not yet upstreamed AND IBM moved forward), do a merge or rebase deliberately. Don't force-push without thinking.

### 3. Rebuild + recreate contextforge

```bash
docker compose -f docker-compose.local.yml build contextforge
docker compose -f docker-compose.local.yml up -d --force-recreate contextforge
docker ps --format '{{.Names}}\t{{.Status}}' | grep contextforge
```

Expected: `Up Xs (healthy)` within ~30s.

### 4. If the container restart-loops on `Multiple head revisions`

This recurs whenever IBM adds a migration whose `down_revision` doesn't chain off our local heads. Standard symptom:

```
Database migration failed: Multiple head revisions are present for given argument 'head';
please specify a specific target revision, '<branchname>@head' to narrow to a specific head,
or 'heads' for all heads
```

`RestartCount` ticks up; logs spam every ~10s.

**Diagnosis** — list current heads inside the running broken container:

```bash
docker exec contextforge-local-contextforge-1 \
    python -m alembic -c mcpgateway/alembic.ini heads
# Expected output: two or more rev IDs, e.g.
#   e28566875fa4 (head)     # ← latest from IBM upstream
#   f0aab1c2d3e4 (head)     # ← from our fork patches
```

**Fix** — generate a metadata-only merge revision joining both heads:

```bash
docker exec contextforge-local-contextforge-1 \
    python -m alembic -c mcpgateway/alembic.ini \
    merge -m "merge <ibm-rev> with l-v-b heads" <ibm-head> <ours-head>
# Creates mcpgateway/alembic/versions/<rev>_merge_*.py
```

Restart so bootstrap_db sees the merge file:

```bash
docker restart contextforge-local-contextforge-1
# Expected: "Running upgrade ... -> <merge-rev>" then app starts cleanly
```

Persist the merge file into the fork so the next build doesn't repeat the discovery:

```bash
docker cp contextforge-local-contextforge-1:/app/mcpgateway/alembic/versions/<rev>_merge_*.py \
    ~/personal/github/mcp-context-forge/mcpgateway/alembic/versions/
```

Then commit it as a fork PR: branch + push + open + squash-merge on `l-v-b/mcp-context-forge` (not IBM upstream). Don't `git add -A` — that picks up the personal experiments stashed in step 1. Use explicit paths:

```bash
git add mcpgateway/alembic/versions/<rev>_merge_*.py
git -c user.email='<you>' -c user.name='<you>' commit -m "Alembic merge: <ibm-rev> + l-v-b heads"
git push fork docs-merge-alembic-<rev>
gh pr create --repo l-v-b/mcp-context-forge --base main --head l-v-b:docs-merge-alembic-<rev>
gh pr merge --squash --delete-branch
```

### 5. Smoke test (post-deploy)

Confirm aggregated server endpoints + mycelium tool count are unchanged:

```bash
curl -s -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":1}' \
    http://localhost:8000/servers/<server_id>/mcp/ | \
    python3 -c 'import sys,json; d=json.load(sys.stdin); print("tools:", len(d["result"]["tools"]))'
```

Expected: same count as before the rebase. If the count drops, walk back through the [source-patch workflow](./SOURCE_PATCH_WORKFLOW.md) to identify which fork patch regressed.

### 6. Restore personal experiments

```bash
git stash pop
```

## Failure modes and recovery

| Symptom | Most likely cause | Fix |
|---|---|---|
| `Updates were rejected because the tip of your current branch is behind` | Local `main` diverged from `fork/main` | `git pull fork main`, then push |
| `Multiple head revisions` after rebuild | New IBM migration doesn't chain off our heads | Step 4 (alembic merge revision) |
| `tool_count` drops after smoke test | A fork patch regressed during merge | `git log fork/main..origin/main` to see what came in; bisect if needed; see fork PRs #1, #2, #4 (instructions/capabilities forwarding + persistence) for the most patch-sensitive paths |
| Container won't start at all | Pre-existing bug landed in upstream | `docker logs contextforge-local-contextforge-1` → check IBM tracker for the regression |

## Why we don't upstream the fork patches

Each fork patch has its own upstream-vs-fork decision:

- PRs #1, #2, #4 (instructions/capabilities forwarding + persistence) — could be upstreamed; flagged as low-priority since IBM hasn't surfaced demand.
- PR #5 (RFC 8414 discovery) — likely valuable upstream; consider proposing once verified in personal use for a few weeks.
- PR #6 (admin form hardening) — small, possibly upstreamable.
- PR #7 (drop admin CSRF + CSP nonce) — deliberate fork-only divergence for the Tailscale-only personal stack. **Do not propose upstream.**

The alembic merge step is the cost we pay for not upstreaming. Worth it for the patches that aren't a fit for IBM.

## When to consider abandoning the fork

If 80%+ of our patches make sense upstream and IBM is responsive, propose them and retire the fork. The CSRF/CSP revert (PR #7) is the only patch that fundamentally requires a fork — everything else could in theory be upstream.
