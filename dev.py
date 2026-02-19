"""Dev server launcher — kills stale processes on port 8000, then starts uvicorn."""

import os
import re
import subprocess
import sys


def kill_port_listeners(port=8000):
    """Find and kill all processes listening on the given port."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        print(f"Warning: could not run netstat: {e}")
        return

    pids = set()
    for line in result.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pid = int(parts[-1])
                    if pid > 0:
                        pids.add(pid)
                except ValueError:
                    continue

    if not pids:
        print(f"No processes listening on port {port}.")
        return

    for pid in sorted(pids):
        print(f"Killing PID {pid} (was listening on port {port})...")
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            print(f"  Warning: could not kill PID {pid}: {e}")

    print()


def main():
    kill_port_listeners(8000)
    print("Starting uvicorn on port 8000...\n")
    os.execvp(sys.executable, [
        sys.executable, "-m", "uvicorn",
        "src.main:app", "--reload", "--port", "8000",
    ])


if __name__ == "__main__":
    main()
