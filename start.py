import os
import sys
import time
import signal
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent


def main():
    env_path = BASE / "backend" / ".env"

    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=str(BASE),
    )


    time.sleep(2)

    frontend = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(BASE / "frontend" / "app.py")],
        cwd=str(BASE),
    )

    def shutdown(*_):
        for p in (frontend, backend):
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        frontend.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
