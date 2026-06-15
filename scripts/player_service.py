from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Any

from fastapi import FastAPI, HTTPException


app = FastAPI(title="FIMS Video Player Service")
_lock = threading.Lock()
_process: subprocess.Popen[bytes] | None = None
_current_source: str | None = None


def _stop_current_process() -> None:
    global _process, _current_source

    if _process and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)

    _process = None
    _current_source = None


def _spawn_player(source: str) -> subprocess.Popen[bytes]:
    player = shutil.which("mpv") or shutil.which("vlc")
    if not player:
        raise RuntimeError("Neither mpv nor vlc is installed")

    if player.endswith("mpv"):
        command = [player, "--fs", "--really-quiet", source]
    else:
        command = [player, "--fullscreen", "--play-and-exit", source]

    return subprocess.Popen(command)


@app.post("/play")
def play(body: dict[str, Any]):
    url = body.get("url")
    file_path = body.get("file_path")
    source = url or file_path
    if not source:
        raise HTTPException(status_code=400, detail="Missing url or file_path")

    global _process, _current_source
    with _lock:
        _stop_current_process()
        try:
            _process = _spawn_player(str(source))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        _current_source = str(source)

    return {"status": "playing", "source": _current_source}


@app.post("/stop")
def stop():
    with _lock:
        _stop_current_process()
    return {"status": "stopped"}


@app.get("/status")
def status():
    running = bool(_process and _process.poll() is None)
    return {
        "status": "playing" if running else "stopped",
        "running": running,
        "source": _current_source,
        "pid": _process.pid if running and _process else None,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
