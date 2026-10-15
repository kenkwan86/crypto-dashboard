# Crypto-Dashboard — fix plan, 2026-10-15

Mode: PLAN
Source review: `reviews/Crypto-Dashboard/2026-10-15-blind.md` (C1, C2 critical and stood refutation; M1, M2 major).
Standard: `reviews/Crypto-Dashboard/standard.md` (plan cap 8; severity anchors at lines 40-45).
User direction (2026-10-15): "go commit for me and plan the fixes. get codex to review/check your plan. once in agreement, continue with the fixes using subagents, then verify".
Revision: 3 (wording updated after round 3), after Codex plan review rounds 1-3 (`## Codex plan review`).

## Where the work happens

- Main repository: `C:\01. Coding\Crypto-Dashboard` (branch `main`). The user's uncommitted work was committed there as `5ab3cf3` on request. The hourly scheduler (`tools/run_hourly.ps1`) commits data on `main` every hour, so executors must NOT edit, run scripts in, or run git commands against this tree.
- Execution target: git worktree `C:\01. Coding\Crypto-Dashboard-fix`, branch `review-fixes-2026-10-15`, created from `5ab3cf3`. Executors may read and write here. Every relative path in this plan is relative to this worktree. Its `data/` is the git-tracked data of `5ab3cf3`; executors must not change `data/`.
- Evidence folder: `C:\01. Coding\EXTERNAL_PROJECT_REVIEW\reviews\Crypto-Dashboard\artifacts\2026-10-15-run` (outside both trees). Executors and verifiers write raw outputs and snapshots here.
- Baseline code for "before" runs: `C:\01. Coding\EXTERNAL_PROJECT_REVIEW\reviews\Crypto-Dashboard\artifacts\copy` holds the same code as `5ab3cf3` (copied before the commit; no `.git`). Copy a new test file there to show it fails on the old code. Do not edit any other file in that copy.
- The plan lives at `reviews/Crypto-Dashboard/2026-10-15-review-plan.md` (this file) and an identical copy at `C:\01. Coding\Crypto-Dashboard-fix\specs\2026-10-15-review-plan.md`. `--plan` for snapshot and check commands is the worktree copy.
- Merge to `main` and any push are NOT part of this plan. They wait for the user after verification.

## Done when

- The plan passes `lint_review.py --strict`. — met (PASS on revision 3)
- Codex reviewed this plan and every Codex objection is resolved or recorded under `## Codex plan review`. — met (round 3: VERDICT: AGREE)
- Each regression item (P1, P3, P4, P5) has a new test that fails on the `5ab3cf3` code and passes on the final worktree, with both outputs saved; P2 (feature) has its tests passing. — not met
- The full test suite passes on the executor's final snapshot. — not met
- `C:\01. Coding\Crypto-Dashboard` has no executor edits: its `git status --porcelain` stays empty apart from the scheduler's own data commits. — not met

## Items

### P1 - Make the hourly job fail loudly when git sync fails

Resolves: C1 (sync failure reported as success); m6 (log trim reads and writes the same file).
Files: `tools/run_hourly.ps1`, new `tests/test_run_hourly.py`, `docs/collectors.md`.
Change: check every git step, never commit non-data files, block sync on a dirty code tree, and record sync status.
- Resolve the repo root from `$PSScriptRoot` (its parent) instead of the hardcoded `C:\01. Coding\Crypto-Dashboard`; log to `<root>\logs\hourly.log`.
- Run `git status --porcelain` first and check its exit code. Ignore lines whose path is under `data/`. If any other line remains (staged, modified or untracked-but-not-ignored), log `sync BLOCKED: uncommitted changes outside data/` and the first 10 paths, run the collector, do NOT run `git add` or `git commit`, skip pull and push, and exit 1. The collected data stays in the working tree.
- On a clean code tree the order is: run the collector, `git add -- data/`, `git commit -m "data: pc hourly collect" -- data/` (pathspec, so already-staged non-data changes can never be included; this also commits data left by an earlier blocked run), `git pull --rebase origin main`, `git push origin main`. There is no pull before the collector: each writer has its own `*-<tag>.parquet` files, so collecting does not need the remote state first, and pending data can never block the pull. Check `$LASTEXITCODE` after every git command. `git commit` exiting 1 with "nothing to commit" counts as success. Any other failure: log `sync FAILED: <step> exit=<code>` and exit 1.
- When a `pull --rebase` fails and a rebase is in progress (`git rev-parse --git-path rebase-merge` or `rebase-apply` exists), run `git rebase --abort` first.
- Write `=== run ok ===` only when every step succeeded.
- After every run write `<root>\logs\sync-status.json` (UTF-8 without BOM): `last_attempt_utc`, `last_success_utc` (carried from the previous file on failure; null if never), `ok` (bool), `error` (string or null).
- Log trim: read the tail into a variable, then write it.
Check: `tests/test_run_hourly.py` (unittest, no test docstrings, no printing inside test methods). Fixtures live in a temporary directory: a bare remote with branch `main`; a clone with local `user.name`/`user.email`, a committed stub `collectors/hourly.py` (appends one line to `data/x.txt`, exits 0), a committed `.gitignore` containing `logs/` and `__pycache__/`, and the script copied from env `RUN_HOURLY_PS1` (default: the worktree's `tools/run_hourly.ps1`) into `<clone>/tools/` and committed, so the fixture starts clean. Rejection hook: `hooks/pre-receive` in the bare remote containing `#!/bin/sh` and `exit 1` (Git for Windows runs it with its bundled sh). Baseline adaptation: the test replaces the literal `C:\01. Coding\Crypto-Dashboard` with the clone root and then asserts that the copied script no longer contains `Crypto-Dashboard`; if it does, the test fails without running it. This is the only change made to the old script, so the old logic runs against the temporary clone and never touches the real repo. The class is skipped when `powershell.exe` is not found; after that check, `setUpClass` prints `P1-powershell-ran` once, before any result line, so a skipped class cannot satisfy the check. Tests:
- `test_clean_tree_pushes_and_records_success`: exit 0; the remote has the data commit; `sync-status.json` has `"ok": true`.
- `test_rejected_push_exits_nonzero`: the bare remote has a `pre-receive` hook that exits 1; exit 1; log has `sync FAILED`; log does not end with `=== run ok ===`; status `"ok": false`.
- `test_rebase_conflict_aborts_and_exits_nonzero`: the clone has an unpushed commit changing `data/x.txt`, and the remote has a different commit changing the same line; exit 1; log has `sync FAILED`; no rebase in progress afterwards.
- `test_dirty_code_tree_blocks_sync`: an uncommitted change to a tracked non-data file; exit 1; log has `sync BLOCKED`; the remote has no new commit.
- `test_staged_code_is_never_committed`: a staged change to a non-data file; exit 1; `git log` of the clone has no new commit containing that file.
- `test_blocked_data_is_synced_after_code_is_resolved`: run once with a dirty non-data file (blocked; data left in the tree), restore that file, run again; the second run exits 0 and the remote's `data/x.txt` holds both runs' lines.
Order: 1.

### P2 - Show sync health on every dashboard page

Resolves: C1 (no one sees the failure); m5 (dead code in `dashboard/shared.py`).
Files: `collectors/run_status.py`, `dashboard/shared.py`, `dashboard/app.py` and `dashboard/pages/*.py` (one call each where missing), new `tests/test_sync_status.py`, `docs/dashboard-and-briefing.md`.
Change: a pure helper decides the message; one shared render function shows it on every page.
- Add `sync_warning(path, now) -> str | None` to `collectors/run_status.py`. Missing file: `None` (cloud or fresh clone). Unparseable file: a warning. `ok` false: a warning at once, naming `error` and `last_success_utc` (or "never succeeded" when it is null). `ok` true but `last_success_utc` older than 3 hours: a warning that sync is overdue. Otherwise `None`.
- Add `render_sync_status()` to `dashboard/shared.py` that calls it with `<repo root>/logs/sync-status.json` and shows `st.error`. `render_freshness()` calls it. Pages that do not call `render_freshness()` (`2_Regime.py`, `6_Research.py`, `7_Coin_Detail.py`) call `render_sync_status()` after `st.title`.
- Delete the unused `STALE_ERROR_HOURS`, `TABLES` and `data_freshness` from `dashboard/shared.py`.
Check: `tests/test_sync_status.py`:
- `test_failed_sync_warns_immediately` (ok false, last success 10 minutes ago: message contains the error text);
- `test_never_succeeded_is_named` (ok false, last success null: message contains "never");
- `test_overdue_success_warns` (ok true, 5 h ago);
- `test_recent_success_is_silent`; `test_missing_file_is_silent`; `test_corrupt_file_warns`;
- `test_render_sync_status_shows_error` (Streamlit `AppTest.from_function` with a self-contained wrapper that imports `dashboard.shared` inside itself, points the status path at a failed-status fixture passed through an environment variable, and calls `render_sync_status()`; after `.run()`, `at.exception` is empty and `at.error` has one element containing the error text);
- `test_every_page_renders_sync_status` (each file in `dashboard/app.py` and `dashboard/pages/*.py` calls `render_freshness(` or `render_sync_status(`).
Order: 2, depends on P1 (file format).

### P3 - Funding: mean of Binance 00/08/16 UTC samples, normalised to 8h, with matching provenance

Resolves: C2 (daily funding value changed venue and hour on 2026-08-25).
Files: `analytics/data_access.py`, `analytics/zscores.py`, `analytics/snapshot.py` (funding provenance and gating only), `briefing/generate.py` (`UNITS["funding"]`), new `tests/test_funding_daily.py`, `docs/analytics.md`, `docs/signals.md`.
Change: one venue and one fixed set of sampling hours for all history, and provenance that describes that input.
- Add `load_daily_funding()` to `analytics/data_access.py`: Binance rows only, from the deduplicated funding table, with `interval_h > 0`, `isfinite(rate)`, and UTC hour in {0, 8, 16}. Every Binance funding schedule (1h, 2h, 4h, 8h) settles at those hours, so the filter does not depend on historical `interval_h` labels, which sweeps and gap fills assign from the current interval (`collectors/hourly.py:148`, `collectors/backfill/binance_vision.py:166`). Value `rate * 8.0 / interval_h`, averaged per `(symbol, UTC day)`; columns `symbol`, `ts` (day), `rate`, `observed_at` (latest included row).
- `funding_zscores()` uses it. `load_funding()` stays unchanged for other callers; cross-venue work stays in `analytics/funding_basis.py`.
- In `annotate_cross_section`: `funding_observed_at` is the latest included Binance settlement row before the cutoff (same filter); drop the `partial venues` rule and the `funding_venues` / `expected_funding_venues` columns; the feed-health check for funding uses only `details` rows with `source == 'binance'`.
- Update `UNITS["funding"]` in `briefing/generate.py` to "mean of Binance 00/08/16 UTC funding samples, normalised to a per-8h rate".
- Known residuals (recorded, not fixed): (a) a live sample written at 00, 08 or 16 UTC can replace the settled value for that key, because both share `symbol, ts, exchange` (finding m1); the daily mean then uses the newest of the two. (b) The per-8h normalisation `rate * 8 / interval_h` still uses the stored label, so a wrong historical label scales that row wrongly. Both predate this plan.
Check: `tests/test_funding_daily.py`, synthetic data in a temporary `DATA_DIR`:
- `test_daily_funding_uses_binance_settlement_mean` (Binance 8h rows at 00/08/16 with .0001/.0002/.0003 plus a Hyperliquid 23:00 row: value is .0002);
- `test_live_sample_hour_is_excluded` (an extra Binance row at 13:00 does not change the value);
- `test_four_hour_coin_uses_00_08_16` (4h coin with rows at 00, 04, ..., 20: value is the mean of the 00, 08 and 16 rows on a per-8h basis);
- `test_interval_change_keeps_same_hours` (a coin labelled 4h on day 1 and 8h on day 2: both days use their 00, 08 and 16 rows);
- `test_duplicate_writer_uses_newest_ingestion` (same key in two files with different `ingested_at`: the newest wins);
- `test_stale_binance_with_fresh_hyperliquid_is_not_eligible` and `test_fresh_binance_with_missing_hyperliquid_is_eligible` (via `annotate_cross_section` with constructed details and complete metrics).
Acceptance reference (`artifacts/prototype3-output.txt`, on worktree data at `5ab3cf3`): Binance rows per coin-day at 00/08/16 number 3 on 74,392 of 74,435 coin-days before 2026-08-25 and on 2,550 of 2,574 coin-days from 2026-08-25 to 2026-10-14; on 2026-10-14 BTC funding z90 is `-2.08` (as built `-0.72`); 15 of 50 coins change side of the 0.75 cutoff. The rerun prints the SHA-256 of every file it reads under `data/funding/`, `data/universe.parquet` and `data/universe_history/`; their first 16 hex digits must equal those in `prototype3-output.txt`, and the executor saves the full hashes and the complete file list in `executor-P3-realdata.txt` for the verifier to compare.
Order: 3.

### P4 - Completed-day freshness instead of a fixed 24-hour age

Resolves: M1 (all coins stale from 23:00 to 24:00 UTC).
Files: `analytics/snapshot.py` (freshness rule), `briefing/generate.py` (`SYSTEM_PROMPT` freshness sentence), new `tests/test_staleness.py`, `docs/analytics.md`.
Change: a completed-day metric is fresh when its observation falls inside the latest completed UTC day.
- In `annotate_cross_section`, keep `{metric}_age_h = now - observed_at` as the displayed actual age. Mark `stale` when `observed_at < now.floor('D') - 1 day` (older than the latest completed day) or `observed_at > now` (future). Remove the `> 24` rule.
- Change the `SYSTEM_PROMPT` sentence "refuse to draw any conclusion from a table whose data is older than 24 hours" so completed-day metrics (cross-section, regime, liquidation history) are judged against the last completed UTC day, while intraday inputs (DVOL, options term structure) keep the 24-hour rule already applied at `analytics/snapshot.py:126`.
Check: `tests/test_staleness.py`, all with healthy coverage details and complete required metrics so that only freshness decides:
- `test_completed_day_inputs_are_eligible_at_2330_utc` (funding 16:00, OI 23:00, price 23:00 of the previous day; now 23:30: `eligible` is True and `data_status` is `healthy`);
- `test_inputs_from_two_days_ago_are_stale` (`data_status` is `stale`);
- `test_age_column_reports_actual_age` (`funding_age_h` equals hours since 16:00 of the previous day);
- `test_just_after_midnight_uses_new_completed_day` (now 00:30 on day D+1: observations from day D are eligible, observations from day D-1 are stale);
- `test_missing_completed_day_input_is_not_eligible` (healthy feeds but no OI observation before the cutoff: not eligible).
Acceptance reference (`artifacts/prototype2-output.txt`): at 2026-10-15 23:30 UTC, 0 of 50 active coins have OI, price or Binance settlement observations outside the latest completed day.
Order: 4, depends on P3 (same function, funding provenance).

### P5 - Store hours without liquidations as zero

Resolves: M2 (quiet coins look stale; quiet days dropped from daily totals).
Files: `collectors/hourly.py` (`collect_coinalyze`), new `tests/test_liquidation_fill.py`, `docs/collectors.md`.
Change: complete hours only, zero-filled per market that returned a valid history.
- Let `current = floor_hour(now)`. Drop any returned point with `t >= current`.
- For each market in the response whose `history` is a list (possibly empty), add a zero row (`long_usd` 0.0, `short_usd` 0.0, `interval` "1h") for every whole hour `t` with `start_s <= t < current` that has no point. A market whose `history` is missing or not a list gets no fill, and the collector prints one warning line for it. Markets absent from the response get no rows. Aggregation by `(symbol, ts, interval)` stays, so several market symbols per base sum correctly.
Check: `tests/test_liquidation_fill.py`, with a stub client (patched `collectors.coinalyze_client.CoinalyzeClient`), `append_parquet` captured, and `COINALYZE_API_KEY` set to a dummy value inside the test only:
- `test_missing_hours_are_stored_as_zero` (BTC points at two hours: 24 BTC rows, 22 zero);
- `test_current_hour_point_is_dropped` (a nonzero point at `now`: no row has `ts == now`);
- `test_empty_history_is_all_zero`; `test_absent_market_is_not_filled`; `test_malformed_history_is_not_filled`;
- `test_two_markets_one_base_sum` (two symbols for BTC, one with a point: 24 rows, the point's value kept);
- `test_quiet_coin_is_healthy_after_fill` (append the filled frame to a temporary `DATA_DIR` and call `coverage_details` one hour later: the coin's liquidations status is `healthy`);
- `test_quiet_day_survives_daily_totals` (a full completed day with two nonzero hours, filled and appended: `daily_liquidations()` returns that day with the two hours' sum).
Order: 5.

```review-proof
{
  "version": 1,
  "phase": "plan",
  "context": "planner: Claude Opus 5.5 review session (main context)",
  "scope": ["tools/run_hourly.ps1", "collectors/run_status.py", "collectors/hourly.py", "dashboard", "analytics/data_access.py", "analytics/zscores.py", "analytics/snapshot.py", "briefing/generate.py", "tests", "docs"],
  "exclusions": ["tests/__pycache__", "dashboard/__pycache__", "dashboard/pages/__pycache__"],
  "items": [
    {
      "id": "P1",
      "depends_on": [],
      "behavior": "In temporary git fixtures with a stub collector, run_hourly.ps1 exits 0 and records ok:true only when every git step succeeds; exits 1 with 'sync FAILED' on a rejected push or a rebase conflict (rebase aborted); exits 1 with 'sync BLOCKED' and commits nothing when non-data files are dirty or staged; the next clean run syncs the data left behind. Requires Windows PowerShell; setUpClass prints P1-powershell-ran once after confirming PowerShell exists. Run with stderr merged into stdout; save to artifacts/2026-10-15-run/executor-P1.txt and verifier-P1.txt.",
      "proof_strategy": "regression",
      "check": {
        "argv": ["python", "-B", "-m", "unittest", "tests.test_run_hourly", "-v"],
        "cwd": ".",
        "location": "read-only",
        "expected_exit": 0,
        "stdout_contains": ["P1-powershell-ran", "test_clean_tree_pushes_and_records_success) ... ok", "test_rejected_push_exits_nonzero) ... ok", "test_rebase_conflict_aborts_and_exits_nonzero) ... ok", "test_dirty_code_tree_blocks_sync) ... ok", "test_staged_code_is_never_committed) ... ok", "test_blocked_data_is_synced_after_code_is_resolved) ... ok", "Ran 6 tests"]
      }
    },
    {
      "id": "P2",
      "depends_on": ["P1"],
      "behavior": "sync_warning warns at once on a failed sync, names 'never' when no sync succeeded, warns when the last success is over 3 hours old or the file is corrupt, and is silent when recent or missing; every dashboard page renders it via st.error. Run with stderr merged into stdout; save to executor-P2.txt and verifier-P2.txt.",
      "proof_strategy": "feature",
      "check": {
        "argv": ["python", "-B", "-m", "unittest", "tests.test_sync_status", "-v"],
        "cwd": ".",
        "location": "read-only",
        "expected_exit": 0,
        "stdout_contains": ["test_failed_sync_warns_immediately) ... ok", "test_never_succeeded_is_named) ... ok", "test_overdue_success_warns) ... ok", "test_recent_success_is_silent) ... ok", "test_missing_file_is_silent) ... ok", "test_corrupt_file_warns) ... ok", "test_render_sync_status_shows_error) ... ok", "test_every_page_renders_sync_status) ... ok", "Ran 8 tests"]
      }
    },
    {
      "id": "P3",
      "depends_on": [],
      "behavior": "funding_zscores uses the per-UTC-day mean of Binance per-8h rates at UTC hours 00/08/16; other venues and Binance rows at hours outside 00/08/16 do not change it; funding provenance and eligibility follow the Binance input. Run with stderr merged into stdout; save to executor-P3.txt and verifier-P3.txt; real-data rerun to executor-P3-realdata.txt and verifier-P3-realdata.txt.",
      "proof_strategy": "regression",
      "check": {
        "argv": ["python", "-B", "-m", "unittest", "tests.test_funding_daily", "-v"],
        "cwd": ".",
        "location": "read-only",
        "expected_exit": 0,
        "stdout_contains": ["test_daily_funding_uses_binance_settlement_mean) ... ok", "test_live_sample_hour_is_excluded) ... ok", "test_four_hour_coin_uses_00_08_16) ... ok", "test_interval_change_keeps_same_hours) ... ok", "test_duplicate_writer_uses_newest_ingestion) ... ok", "test_stale_binance_with_fresh_hyperliquid_is_not_eligible) ... ok", "test_fresh_binance_with_missing_hyperliquid_is_eligible) ... ok", "Ran 7 tests"]
      }
    },
    {
      "id": "P4",
      "depends_on": ["P3"],
      "behavior": "A coin whose inputs fall inside the latest completed UTC day is eligible at 23:30 UTC; inputs from two days ago are stale; the age column still reports actual age. Run with stderr merged into stdout; save to executor-P4.txt and verifier-P4.txt.",
      "proof_strategy": "regression",
      "check": {
        "argv": ["python", "-B", "-m", "unittest", "tests.test_staleness", "-v"],
        "cwd": ".",
        "location": "read-only",
        "expected_exit": 0,
        "stdout_contains": ["test_completed_day_inputs_are_eligible_at_2330_utc) ... ok", "test_inputs_from_two_days_ago_are_stale) ... ok", "test_age_column_reports_actual_age) ... ok", "test_just_after_midnight_uses_new_completed_day) ... ok", "test_missing_completed_day_input_is_not_eligible) ... ok", "Ran 5 tests"]
      }
    },
    {
      "id": "P5",
      "depends_on": [],
      "behavior": "collect_coinalyze drops current-hour points and zero-fills every complete hour without a point for markets that returned a valid history list; absent or malformed markets get no rows; a filled quiet coin is healthy in coverage. Run with stderr merged into stdout; save to executor-P5.txt and verifier-P5.txt.",
      "proof_strategy": "regression",
      "check": {
        "argv": ["python", "-B", "-m", "unittest", "tests.test_liquidation_fill", "-v"],
        "cwd": ".",
        "location": "read-only",
        "expected_exit": 0,
        "stdout_contains": ["test_missing_hours_are_stored_as_zero) ... ok", "test_current_hour_point_is_dropped) ... ok", "test_empty_history_is_all_zero) ... ok", "test_absent_market_is_not_filled) ... ok", "test_malformed_history_is_not_filled) ... ok", "test_two_markets_one_base_sum) ... ok", "test_quiet_coin_is_healthy_after_fill) ... ok", "test_quiet_day_survives_daily_totals) ... ok", "Ran 8 tests"]
      }
    }
  ]
}
```

## Proof rules for the executors

- Capture: run each check with `subprocess.run(argv, cwd=<worktree>, stdout=PIPE, stderr=STDOUT, env={..., "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})` and save the exact bytes. stderr is merged into stdout on purpose because `unittest -v` writes results to stderr.
- Regression proof (P1, P3, P4, P5): before changing code, copy the new test file into `artifacts/copy/tests/` and run the same argv with `cwd` = `artifacts/copy`; save as `executor-P<n>-before.txt`. It must fail for the defect the item fixes, not for an import error alone; when the new test imports a function that does not exist yet, add one assertion-level test in the same file that exercises the old public entry point (for example `funding_zscores()` for P3) so the old behavior is shown to be wrong. For P1 set `RUN_HOURLY_PS1` to `artifacts/copy/tools/run_hourly.ps1`.
- P2 is a feature: there is no old behavior to fail.
- New tests have no docstrings and print nothing inside test methods, so each verbose result line stays `<name> (<qualified name>) ... ok`.
- Linux: P1 tests skip without PowerShell. A skipped P1 run is unverified, never Passed.
- Full suite: `python -B -m unittest discover -s tests -v` on the final worktree, saved as `executor-full-suite.txt`.
- Commit the changes on branch `review-fixes-2026-10-15` in the worktree, then take the final snapshot: `python -B "C:\01. Coding\EXTERNAL_PROJECT_REVIEW\tools\check_review_proof.py" snapshot --plan "C:\01. Coding\Crypto-Dashboard-fix\specs\2026-10-15-review-plan.md" --target "C:\01. Coding\Crypto-Dashboard-fix" --output <evidence>\executor-final.json`. No commits after it. No merge to `main`, no push.
- Never read `.env`. Never use `rm`; delete temporary files with PowerShell `Remove-Item`.

## Not doing

- m1 (sweep and live sample share a key): recorded as a known residual under P3. Adding a `kind` column changes the storage schema of every writer. Deferred.
- m2 (duplicate `fetch_funding_rates` call): run time only. Below the cap.
- m3 (`analytics/vol.py:110` `.last()` mixes rows): affects only the CLI. Below the cap.
- m4 (unpinned dependencies, Python 3.12 vs 3.13): needs the user's upgrade policy. Deferred to the user.
- Running the collector from a separate data-only clone: changes the Windows Task Scheduler setup outside the repository. P1 makes failures visible and stops committing non-data files; the clone is a user decision.
- Refilling historic liquidation gaps: Coinalyze hourly retention limits a refetch; P5 fixes data from now on. The 20-row rule in `analytics/liquidations.py:33` stays.
- Showing Linux/cloud sync status: the cloud workflow does not run `run_hourly.ps1`; `sync_warning` is silent when the file is missing.
- Merge and push: wait for the user.

## Simpler alternative considered

For C2, the plain Binance daily mean over all rows was the first draft; Codex showed it still mixes 3 settlement rows per day before 2026-08-25 with about 11 mixed rows after, so the settlement-hour filter was added. Keeping the cross-venue average was rejected because only Binance has history before 2026-08-25. For M1, a 26-hour limit or an end-of-hour offset were considered; the first draft used the offset, and Codex showed it is wrong for funding observed at 16:00. The completed-day rule states the meaning directly. For C1, checking `$LASTEXITCODE` alone was considered; it would still let a dirty or staged code tree be committed or block every run silently.

## Codex plan review

Round 1 (`artifacts/2026-10-15-run/codex-plan-review-01-reply.md`, gpt-6-astra, read-only): VERDICT: CHANGES REQUIRED, 9 blocking, 2 suggestions. Dispositions:

1. P1 baseline could run against the real checkout — accepted: the test rewrites the hardcoded path into the temporary clone and refuses to run if any `Crypto-Dashboard` literal remains.
2. P1 failure fixture not deterministic — accepted: `pre-receive` hook for push rejection, a separate divergent-history fixture for rebase conflict, abort asserted, stub and `.gitignore` committed.
3. P1 could commit staged user code — accepted: blocked runs never add or commit; clean runs commit with `-- data/` pathspec; `git status` and `git add` exit codes checked; staged-code fixture added.
4. P2 silent after a fresh failure and missing pages — accepted: immediate warning on `ok:false`, "never succeeded" message, `render_sync_status()` on every page, AppTest and page-coverage tests.
5. P3 mixed sampling — accepted: settlement-hour filter; prototype shows median 3.0 rows per day before and after; live-sample, duplicate-writer and 4h tests added; residual m1 ambiguity recorded.
6. P3 provenance and gating on wrong inputs — accepted: funding provenance and feed check use Binance only; two eligibility tests added.
7. P4 end-of-hour semantics — accepted: completed-day rule replaces the age offset; briefing sentence updated; tests assert `eligible`.
8. P5 current-hour assertion — accepted: returned current-hour points are dropped; fixture includes one.
9. P5 coverage (suggestion) — accepted: empty, malformed, two-markets and health tests added.
10. Linux skips satisfy predicates — accepted: `P1-powershell-ran` marker and `Ran 5 tests` required; skipped runs are unverified.
11. Proof contradictions and frozen inputs (suggestion) — accepted: Done-when wording fixed, plan path stated, real-data inputs pinned to git-tracked `5ab3cf3` data with `git ls-tree` recorded.

Round 2 (`artifacts/2026-10-15-run/codex-plan-review-02.jsonl`, same thread): VERDICT: CHANGES REQUIRED, 2 blocking, 5 suggestions. Dispositions:

1. P1 blocked data would stop the next pull — accepted: no pull before the collector; data is committed with the pathspec before pull --rebase; two-run recovery test added.
2. P3 filter relied on historical interval labels — accepted: fixed UTC hours 00/08/16, valid for every Binance schedule; prototype3 shows 3 rows on 99.9% of coin-days before 2026-08-25 and 99.1% after; interval-change test added; label-based normalisation recorded as a residual.
3. P1 fixture isolation (suggestion) — accepted: adapted script committed, `main` branch, local git identity, sh hook.
4. P4 midnight boundary (suggestion) — accepted: two tests added; the briefing keeps the 24-hour rule for intraday options inputs.
5. P2 AppTest wrapper (suggestion) — accepted: self-contained wrapper; `at.exception` empty asserted.
6. Output literals (suggestion) — accepted: no docstrings, no prints in tests, marker printed in `setUpClass`.
7. Evidence details (suggestion) — accepted: the rerun hashes the actual input files; daily-total survival test added.

Round 3 (`artifacts/2026-10-15-run/codex-plan-review-03-reply.md`, same thread): VERDICT: AGREE, no blocking objections, 4 suggestions. Applied: marker wording aligned to `setUpClass`; P3 named as a fixed-hour sampled mean in the title, briefing units and JSON; full input hashes saved in executor evidence. Suggestion 4 (agreement is not execution proof) is a reminder, kept as stated in SCOPE.

## SCOPE

- Covers C1, C2, M1, M2 and the minor items m5 and m6 that touch the same files. Other minor findings are under Not doing.
- The P3 real-data effect is pinned to 2026-10-14 on the git-tracked `5ab3cf3` data in the worktree.
- P1 is tested against temporary git repositories, not GitHub or Task Scheduler; how Task Scheduler reports exit 1 is not tested. P1 needs Windows PowerShell to be verified.
- Falsifying evidence: a regression test that passes on the `5ab3cf3` copy; a full-suite failure; BTC z90 on 2026-10-14 different from `-2.08` after P3 on inputs whose hashes match `prototype3-output.txt`; any executor edit in `C:\01. Coding\Crypto-Dashboard`.
