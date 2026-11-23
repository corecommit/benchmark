#!/usr/bin/env python3
"""Aggregate benchmarks/tmp/*.json into benchmarks/SUMMARY.md and clean up."""
import datetime
import glob
import json
import os
import sys
from pathlib import Path

TMP_DIR = Path("benchmarks/tmp")
BENCH_DIR = Path("benchmarks")
OS_FAMILIES = ("Linux", "Windows")
EMOJI = {"Linux": "🐧", "Windows": "🪟"}

HEADERS = [
    "Runner", "OS Version", "Arch", "Cores", "RAM (GB)",
    "CPU (s)", "Disk W (MB/s)", "Disk R (MB/s)", "Mem (s)",
]

# (title, metric, best mode, unit, hint)
CATEGORIES = [
    ("CPU", "cpu_bench_seconds", "min", "s", "lower is better"),
    ("Disk write", "disk_write_mbps", "max", " MB/s", "higher is better"),
    ("Disk read", "disk_read_mbps", "max", " MB/s", "higher is better"),
    ("Memory", "memory_200mb_seconds", "min", "s", "lower is better"),
]


def load_results() -> list[dict]:
    files = sorted(glob.glob(str(TMP_DIR / "*.json")))
    print(f"[info] found {len(files)} benchmark file(s): {files}")

    if not files:
        print("ERROR: no benchmark JSON files found in benchmarks/tmp/", file=sys.stderr)
        print("This usually means the benchmark jobs failed to commit,", file=sys.stderr)
        print("or the checkout is on a stale commit.", file=sys.stderr)
        sys.exit(1)

    return [json.loads(Path(f).read_text()) for f in files]


def group_by_os(rows: list[dict]) -> dict[str, list[dict]]:
    sections: dict[str, list[dict]] = {family: [] for family in OS_FAMILIES}
    for r in rows:
        sections.setdefault(r.get("os", "Other"), []).append(r)
    for items in sections.values():
        items.sort(key=lambda r: r.get("runner_label", ""))
    return sections


def best(rows: list[dict], metric: str, mode: str) -> tuple:
    values = [(r[metric], r.get("runner_label"))
              for r in rows if r.get(metric) is not None]
    if not values:
        return (None, None)
    return min(values) if mode == "min" else max(values)


def fmt_best(pair: tuple, unit: str) -> str:
    value, label = pair
    if value is None or label is None:
        return "—"
    return f"{label} ({value}{unit})"


def render_table(items: list[dict]) -> list[str]:
    lines = [
        "| " + " | ".join(HEADERS) + " |",
        "|" + "|".join(["---"] * len(HEADERS)) + "|",
    ]
    for r in items:
        cells = [
            f"`{r.get('runner_label', '')}`",
            (r.get("os_version") or "")[:60],
            r.get("arch", ""),
            r.get("cpu_cores", ""),
            r.get("ram_gb", ""),
            r.get("cpu_bench_seconds", ""),
            r.get("disk_write_mbps", ""),
            r.get("disk_read_mbps", ""),
            r.get("memory_200mb_seconds", ""),
        ]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    return lines


def build_markdown(rows: list[dict]) -> str:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")

    lines = [
        "# GitHub-Hosted Runner Benchmark\n",
        f"_Generated: {now} | Run: {run_id}_\n",
        "## 🏆 Fastest by Category\n",
    ]
    for title, metric, mode, unit, hint in CATEGORIES:
        winner = fmt_best(best(rows, metric, mode), unit)
        lines.append(f"- **{title} ({hint}):** {winner}")
    lines.append("")

    sections = group_by_os(rows)
    for family in OS_FAMILIES:
        items = sections.get(family, [])
        if not items:
            continue
        lines.append(f"## {EMOJI.get(family, '')} {family}\n")
        lines.extend(render_table(items))
        lines.append("")

    return "\n".join(lines)


def cleanup() -> None:
    for f in glob.glob(str(TMP_DIR / "*.json")) + glob.glob(str(BENCH_DIR / "*.json")):
        os.remove(f)
    try:
        TMP_DIR.rmdir()
    except OSError:
        pass


def main() -> None:
    rows = load_results()
    markdown = build_markdown(rows)

    BENCH_DIR.mkdir(exist_ok=True)
    (BENCH_DIR / "SUMMARY.md").write_text(markdown)

    cleanup()
    print(markdown)


if __name__ == "__main__":
    main()
