"""Live progress bar for a monthly-refresh run (P24): `uv run python -m tpt.ci.watch [RUN_ID]`.

GitHub exposes step status (not live log lines) while a job runs, so the bar counts steps of the
refresh job and shows how long the current step has been going. Default: the latest run.
"""

import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime

WORKFLOW = "monthly_refresh.yml"


def bar(done: int, total: int, width: int = 30) -> str:
    filled = round(width * done / total) if total else 0
    return f"[{'#' * filled}{'-' * (width - filled)}] {done}/{total}"


def minutes(start: str | None, now: datetime) -> str:
    if not start:
        return "-"
    s = (now - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds()
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}m"


def _gh(*args: str) -> dict | list:
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True,
                                     text=True).stdout)  # fmt: skip


def main() -> None:
    run = sys.argv[1] if len(sys.argv) > 1 else str(_gh(
        "run", "list", "--workflow", WORKFLOW, "--limit", "1", "--json", "databaseId")[0][
        "databaseId"])  # fmt: skip
    while True:
        r = _gh("run", "view", run, "--json", "status,conclusion,jobs,url")
        job = next((j for j in r["jobs"] if j["name"] == "refresh"), None)
        now = datetime.now(UTC)
        if job:
            steps = job["steps"]
            done = sum(s["status"] == "completed" for s in steps)
            cur = next((s for s in steps if s["status"] == "in_progress"), None)
            step = f"{cur['name'][:40]} {minutes(cur['startedAt'], now)}" if cur else ""
            line = f"{bar(done, len(steps))}  job {minutes(job['startedAt'], now)}  {step}"
        else:
            line = f"waiting for refresh job ({r['status']})"
        cols = shutil.get_terminal_size().columns - 1  # never wrap, so \r redraws in place
        print(f"\r{line[:cols]:<{cols}}", end="", flush=True)
        if r["status"] == "completed":
            print(f"\nrun {run}: {r['conclusion']}  {r['url']}")
            for j in r["jobs"]:
                print(f"  {j['name']:<15} {j['conclusion']}")
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
