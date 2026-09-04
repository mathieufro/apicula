# `fuzz/gw5ast138c/harness/` — the published batch contract

This file is the **single published contract** for the harness batch entry
point (`F11`, cross-phase `F29`, `P0.T22`). Every later phase's batch
invocation quotes *this file* and nothing else, rather than re-deriving the
surface. `tests/test_batch.py::test_batch_cli_readme_matches_parser` asserts
the option table below and `__main__.build_parser()` agree, so the contract
cannot drift from the code.

## Canonical spellings (binding on every later phase)

| Thing | Canonical | Never |
|---|---|---|
| batch entry point | `python -m fuzz.gw5ast138c.harness` | `...harness.__main__` |
| design flag | `--design-dir` | `--design` (that belongs to `equiv.py`) |
| batch flag | `--batch-id` | `--batch` |
| stall watchdog | `fuzz/gw5ast138c/harness/watchdog.sh` | `$PIPE/tools/watchdog.sh` (`F30`) |

## The published CLI — exactly these seven options, no synonyms

| Flag | Shape | Required |
|---|---|---|
| `--design-dir <path>` | absolute scratch/design directory | yes |
| `--shape <name>` | a module name under `fuzz/gw5ast138c/shapes/` | yes |
| `--sweep-points <int>` | number of sweep points; default = the shape's full `sweep_values` length | no |
| `--level {E0,E1,E2}` | comparison level; default `E1` | no |
| `--batch-id <str>` | batch id; also names `$PIPE/evidence/_runs/<batch_id>.log` | yes |
| `--detach` | run detached with the out-of-process watchdog armed first | no |
| `--expected-minutes <int>` | expected wall clock; sets the watchdog's `stall = D/10` | required with `--detach` |

```sh
cd $FL/apicula
export GOWINHOME=/Applications/GowinIDE.app/Contents/Resources/Gowin_EDA
export DYLD_LIBRARY_PATH=$GOWINHOME/IDE/lib
export DYLD_FRAMEWORK_PATH=$GOWINHOME/IDE/lib
vendor/venv/bin/python -m fuzz.gw5ast138c.harness \
    --design-dir $DATASTORE/batch/smoke-001 --shape smoke \
    --batch-id smoke-001 --level E1 --detach --expected-minutes 60
```

`--detach` returns immediately after printing `BATCH_DETACHED`, the batch pid,
the watchdog pid and the three log paths.

## Files one batch owns, all under `$PIPE/evidence/_runs/`

| File | Contents |
|---|---|
| `<batch_id>.log` | the batch log — a **file**, never a filter pipe |
| `<batch_id>.watchdog.log` | the out-of-process watchdog's own log |
| `<batch_id>.pid` | the batch pid, published *after* the watchdog is armed |
| `<batch_id>.stdout.log` | the detached child's stdout/stderr |
| `<batch_id>.rows.jsonl` | one evidence row per executed run (the resume ledger) |

## Long-running discipline (`spec-harness.md` §8)

* The watchdog (`watchdog.sh`) is armed **before** the batch starts and runs as
  a separate process. It takes a *pidfile*, not a pid, which is what makes
  "armed first" literally true; a pid that never appears is a death.
* It judges liveness only from the batch pid and log-file mtimes — never from
  anything the batch says about itself.
* Intervals: `stall = expected_duration / 10`, floored at 5 min, capped at
  90 min; `poll = min(300 s, stall / 3)`. Death and completion are additionally
  checked on a 2 s tick, so a death is never hidden for a whole stall poll; the
  `poll` cadence governs the **stall** check, which is what the formula is for.
* Log vocabulary, greppable:
  * `WATCHDOG_ARMED batch=<id> stall=<n>min poll=<n>s`
  * `WATCHDOG_STALL batch=<id> newest=<file> age=<n>min`
  * `WATCHDOG_DEAD batch=<id> exited WITHOUT BATCH_COMPLETE`
  * `WATCHDOG_COMPLETE batch=<id> saw BATCH_COMPLETE (clean exit)`
* The batch's last act is exactly one line
  `BATCH_COMPLETE <batch_id> runs=<n> ok=<n> diff=<n> aborted=<n>`, with
  `runs == ok + diff + aborted`. The watchdog's clean-exit verdict is the
  **presence of that line**, not the process having exited.

## Batch head (`roadmap.md` §5.1c / §9)

In this order and unconditionally, before any row the batch would produce:
`selftest --inject-one-fuse`, `selftest --unpacker-completeness`, then the
`gw_sh` pre-flight. A gate that **fails** blocks every row (the batch writes
`BATCH_COMPLETE ... runs=0` and exits non-zero). A gate whose owning task has
not landed yet (`selftest` is a `P0.T18` stub until `P0.T29`) is recorded
`UNAVAILABLE` with a printed warning and does not block, because a gate cannot
have an opinion before it exists.

## Resumability

A batch is a **list of run ids** (`<batch_id>-<shape>-<nnnn>`). A run whose row
in `<batch_id>.rows.jsonl` already carries a terminal verdict
(`ok` | `diff` | `aborted` | `refused`) is skipped, so a killed batch is
restarted with the **identical command**.

## Batch sizing (`D51`)

`batch_runs = floor(10 h * parallelism / measured_per_run_total)` at
`parallelism = 1` until measured. The per-run cost is read from `P0.T34`'s
`$PIPE/evidence/calibration/measured-budget.md` when it exists; otherwise the
`spec.md` §8.2 ASSUMED number is used and a warning is printed.

## Test-only environment hooks

These are environment variables, not CLI flags, precisely so the published
surface stays exactly seven options.

| Variable | Effect |
|---|---|
| `FUZZ_HARNESS_RUNS_DIR` | overrides `$PIPE/evidence/_runs` |
| `FUZZ_HARNESS_FAKE_RUN_SECONDS` | each run sleeps this long and returns a synthetic `ok` row; the batch head is skipped |
