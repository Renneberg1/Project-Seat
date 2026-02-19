"""Dev server launcher — kills stale processes on port 8000, then starts uvicorn."""

import subprocess
import sys


def kill_port_listeners(port=8000):
    """Find and kill all processes listening on the given port.

    Uses /F /T to force-kill entire process trees.
    Returns True if the port is free after cleanup.
    """
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        print(f"Warning: could not run netstat: {e}")
        return True

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
        return True

    for pid in sorted(pids):
        print(f"Killing PID {pid} (was listening on port {port})...")
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            print(f"  Warning: could not kill PID {pid}: {e}")

    # Verify port is actually free
    import time
    time.sleep(1)
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                print(f"\nWarning: port {port} still occupied by zombie processes.")
                return False
    except Exception:
        pass

    print()
    return True


def main():
    port = 8000
    port_free = kill_port_listeners(port)
    if not port_free:
        port = 8001
        kill_port_listeners(port)
        print(f"Falling back to port {port}.\n")
    print(f"Starting uvicorn on port {port}...\n")
    # Use subprocess.run instead of os.execvp so the parent process stays
    # alive.  On Windows, execvp can orphan uvicorn's reload child processes,
    # creating zombie listeners that are nearly impossible to kill.
    try:
        subprocess.run(
            [sys.executable, "-m", "uvicorn",
             "src.main:app", "--reload", "--port", str(port)],
        )
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
