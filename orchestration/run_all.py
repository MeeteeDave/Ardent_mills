"""
===============================================================================
 Script Name   : run_all.py
 Project       : Ardent Mills ETL - orchestration
 Description   : Runs the pipeline end to end, stopping at the first failure so
                 the OLAP layer is never built on a half-loaded OLTP layer.

                 Two stages, and the order is not cosmetic:
                   * OLTP  - Excel -> ARD_OPS_* via MERGE/upsert
                   * OLAP  - RUN_INCREMENTAL_OLAP_LOAD, which loads all 11
                             dimensions before all 5 facts. A fact resolves its
                             foreign keys by looking the business key up in the
                             dimension, so a fact built on a stale dimension
                             drops or misassigns rows.

                 Stage 02 is invoked with --skip-oltp because stage 01 has
                 already done the OLTP load; without it the Excel load runs
                 twice.

                 Run history goes to the database, not to local files:
                 ETL_AUDIT (one row per run), ETL_ERROR (one row per failure),
                 ETL_LOAD_CONTROL (the incremental watermark).

 Usage         : py orchestration/run_all.py
                 py orchestration/run_all.py --only oltp
                 py orchestration/run_all.py --validate-only
                 py orchestration/run_all.py -v
===============================================================================
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)

# (key, script, friendly name, extra args)
STAGES = [
    ("oltp", "01_oltp_load_pipeline.py", "OLTP  Excel -> ARD_OPS_*", []),
    ("olap", "02_oltp_to_olap_incremental_pipeline.py", "OLAP  dims -> facts", ["--skip-oltp"]),
]

# Log lines worth surfacing as the one-line progress summary.
_HINTS = ("Reading source", "Loading ARD_OPS", "Running RUN_INCREMENTAL",
          "Audit row written", "finished successfully", "Batch id")


def _summary(output: str) -> str:
    """The one line worth showing: what the stage actually did."""
    for line in reversed(output.splitlines()):
        if "finished successfully" in line:
            return "ok"
        if "validate-only" in line:
            return "validated, no database writes"
    return "done"


def _failure_reason(output: str) -> str:
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if any(m in line for m in ("Error:", "ERROR -", "Exception:", "ORA-", "Traceback")):
            return line[:200]
    return ""


def _run(script: Path, extra: list[str], verbose: bool) -> tuple[int, str, float]:
    cmd = [str(PYTHON), "-u", str(script), *extra]
    t0 = time.time()
    proc = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    if verbose:
        for raw in proc.stdout.splitlines():
            print(f"      | {raw}")
    return proc.returncode, proc.stdout, time.time() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the Ardent Mills pipeline end to end.")
    ap.add_argument("--only", choices=[k for k, *_ in STAGES], help="run just one stage")
    ap.add_argument("--validate-only", action="store_true",
                    help="transform and validate without writing to Oracle")
    ap.add_argument("--skip-connection-test", action="store_true")
    ap.add_argument("--excel", help="override the source workbook path")
    ap.add_argument("--force", action="store_true",
                    help="reload even if these exact bytes already loaded")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="show every log line instead of one line per stage")
    args = ap.parse_args()

    passthrough: list[str] = []
    if args.validate_only:
        passthrough.append("--validate-only")
    if args.skip_connection_test:
        passthrough.append("--skip-connection-test")
    if args.excel:
        passthrough += ["--excel", args.excel]
    if args.force:
        passthrough.append("--force")

    chain = [s for s in STAGES if not args.only or s[0] == args.only]

    print("=" * 78)
    print(f"ARDENT MILLS ETL    {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("=" * 78)
    mode = "validate only (no database writes)" if args.validate_only else "full load"
    print(f"  {len(chain)} stage(s), {mode}, stop on first failure")

    t_run = time.time()
    for i, (key, script, name, extra) in enumerate(chain, 1):
        path = PROJECT_ROOT / "production_pipelines" / script
        if not path.exists():
            print(f"   [{i}/{len(chain)}] {name} ... MISSING {path}")
            return 1

        # --skip-oltp only makes sense when stage 01 ran first in this same chain
        stage_extra = [a for a in extra if not (a == "--skip-oltp" and args.only == "olap")]
        label = f"   [{i}/{len(chain)}] {name} "
        label += "." * max(2, 44 - len(label)) + " "
        print(label, end="", flush=True)

        code, out, secs = _run(path, stage_extra + passthrough, args.verbose)
        if code != 0:
            print(f"FAILED {secs:>7.1f}s")
            print(f"\n   what went wrong: {_failure_reason(out) or 'see the log file'}")
            print(f"   stage          : production_pipelines/{script}")
            if not args.verbose:
                print("   re-run with -v to see the full output")
            print(f"\n   stopped here - {len(chain) - i} stage(s) did NOT run")
            return 1
        print(f"{_summary(out):<28}{secs:>7.1f}s")

    print("\n" + "=" * 78)
    print(f"ALL STAGES SUCCEEDED    {time.time() - t_run:.1f}s")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
