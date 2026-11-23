#!/usr/bin/env python3
"""Cross-platform benchmark for GitHub-hosted runners (Linux / Windows).

Writes the results to benchmarks/tmp/<runner_label>.json
"""
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

OUTPUT_DIR = Path("benchmarks/tmp")
IS_LINUX = platform.system() == "Linux"
IS_WINDOWS = platform.system() == "Windows"

MB = 1024 * 1024
GB = 1024**3


# --------------------------------------------------------------------------
# System info
# --------------------------------------------------------------------------
def detect_cpu() -> dict:
    """Return CPU model and core count."""
    cores = os.cpu_count()
    model = None

    if IS_LINUX:
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        model = line.split(":", 1)[1].strip()
                        break
        except FileNotFoundError:
            pass
    elif IS_WINDOWS:
        model = platform.processor()

    return {"cpu_model": model, "cpu_cores": cores}


def _ram_linux() -> float | None:
    # 1) cgroup limits (containers)
    for path in (
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    ):
        try:
            value = Path(path).read_text().strip()
            if value and value != "max":
                n = int(value)
                if 0 < n < (1 << 60):
                    return round(n / GB, 1)
        except (FileNotFoundError, PermissionError, ValueError):
            pass

    # 2) /proc/meminfo
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return round(int(line.split()[1]) / 1024**2, 1)
    except FileNotFoundError:
        pass
    return None


def _ram_windows_powershell() -> float | None:
    try:
        out = subprocess.check_output(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory",
            ],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        if out.isdigit():
            return round(int(out) / GB, 1)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return None


def _ram_windows_ctypes() -> float | None:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return round(stat.ullTotalPhys / GB, 1)
    except Exception:
        pass
    return None


def detect_ram_gb() -> float | None:
    if IS_LINUX:
        return _ram_linux()
    if IS_WINDOWS:
        return _ram_windows_powershell() or _ram_windows_ctypes()
    return None


def collect_system_info() -> dict:
    info = {
        "runner_label": os.environ.get("MATRIX_LABEL", "unknown"),
        "os": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }
    info.update(detect_cpu())
    info["ram_gb"] = detect_ram_gb()
    if info["ram_gb"] is None:
        print("[warn] RAM detection failed", file=sys.stderr)
    return info


# --------------------------------------------------------------------------
# Benchmarks
# --------------------------------------------------------------------------
def bench_cpu(iterations: int = 20_000) -> float:
    """SHA-256 over 1 KiB, repeated `iterations` times."""
    data = b"x" * 1024
    start = time.perf_counter()
    for _ in range(iterations):
        hashlib.sha256(data).hexdigest()
    return round(time.perf_counter() - start, 4)


def bench_disk(size_mb: int = 100) -> dict:
    """Sequential write and read of `size_mb` MiB in the temp directory."""
    filepath = Path(tempfile.gettempdir()) / "bench_disk.bin"
    chunk = os.urandom(MB)

    start = time.perf_counter()
    with open(filepath, "wb") as f:
        for _ in range(size_mb):
            f.write(chunk)
    write_time = time.perf_counter() - start

    start = time.perf_counter()
    with open(filepath, "rb") as f:
        while f.read(MB):
            pass
    read_time = time.perf_counter() - start

    filepath.unlink()
    return {
        "disk_write_mbps": round(size_mb / write_time, 1) if write_time else None,
        "disk_read_mbps": round(size_mb / read_time, 1) if read_time else None,
    }


def bench_memory(size_mb: int = 200) -> float:
    """Allocate `size_mb` MiB and touch one byte per 4 KiB page."""
    start = time.perf_counter()
    block = bytearray(size_mb * MB)
    for i in range(0, len(block), 4096):
        block[i] = 1
    elapsed = round(time.perf_counter() - start, 4)
    del block
    return elapsed


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    info = collect_system_info()
    info["cpu_bench_seconds"] = bench_cpu()
    info.update(bench_disk())
    info["memory_200mb_seconds"] = bench_memory()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{info['runner_label']}.json"
    output_file.write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()