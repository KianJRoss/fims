from __future__ import annotations

import glob
import os
import random
import subprocess
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException


VIDEO_DIR = "/media/pi/VIDEOS/videos"
IDLE_RETURN_SECONDS = 60
IDLE_POLL_SECONDS = 0.5

app = FastAPI(title="FIMS Video Kiosk Player Service")

_lock = threading.Lock()
_trigger_event = threading.Event()
_current_proc: subprocess.Popen[bytes] | None = None
_current_source: str | None = None
_mode = "idle"
_idle_playlist: list[str] = []
_idle_timer: threading.Timer | None = None
_idle_timer_generation = 0
_idle_thread_started = False


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    env.setdefault("DISPLAY", ":0")
    return env


def _spawn_mpv(path: str, loop_forever: bool = False) -> subprocess.Popen[bytes]:
    command = ["mpv", "--fs", "--really-quiet", "--no-terminal"]
    if loop_forever:
        command.append("--loop-file=inf")
    command.append(path)
    return subprocess.Popen(command, env=_build_env())


def _stop_current_process_locked() -> None:
    global _current_proc, _current_source

    proc = _current_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    _current_proc = None
    _current_source = None


def _cleanup_finished_process_locked() -> None:
    global _current_proc, _current_source

    if _current_proc is not None and _current_proc.poll() is not None:
        _current_proc = None
        _current_source = None


def _cancel_idle_timer_locked() -> None:
    global _idle_timer

    if _idle_timer is not None:
        _idle_timer.cancel()
        _idle_timer = None


def _set_idle_return_timer_locked() -> None:
    global _idle_timer, _idle_timer_generation

    _cancel_idle_timer_locked()
    _idle_timer_generation += 1
    generation = _idle_timer_generation
    timer = threading.Timer(IDLE_RETURN_SECONDS, _idle_timeout, args=(generation,))
    timer.daemon = True
    _idle_timer = timer
    timer.start()


def _idle_timeout(generation: int) -> None:
    global _mode, _idle_timer

    with _lock:
        if generation != _idle_timer_generation:
            return

        _idle_timer = None
        _trigger_event.clear()
        _mode = "idle"
        _stop_current_process_locked()


def _start_triggered_playback_locked(source: str) -> None:
    global _current_proc, _current_source, _mode

    _cancel_idle_timer_locked()
    _stop_current_process_locked()
    _trigger_event.set()
    _mode = "triggered"

    proc = _spawn_mpv(source, loop_forever=True)
    _current_proc = proc
    _current_source = source
    _set_idle_return_timer_locked()


def _pick_idle_source_locked() -> str | None:
    playlist = list(_idle_playlist)
    if playlist:
        random.shuffle(playlist)
        return playlist.pop()

    files = glob.glob(os.path.join(VIDEO_DIR, "*.mp4"))
    if files:
        random.shuffle(files)
        return files.pop()

    return None


def _idle_loop() -> None:
    global _current_proc, _current_source, _mode

    while True:
        if _trigger_event.is_set():
            time.sleep(IDLE_POLL_SECONDS)
            continue

        with _lock:
            _cleanup_finished_process_locked()
            source = _pick_idle_source_locked()

        if _trigger_event.is_set():
            time.sleep(IDLE_POLL_SECONDS)
            continue

        if source is None:
            time.sleep(IDLE_POLL_SECONDS)
            continue

        with _lock:
            if _trigger_event.is_set() or _mode == "triggered":
                continue
            _cleanup_finished_process_locked()
            try:
                proc = _spawn_mpv(source, loop_forever=False)
            except Exception:
                _current_proc = None
                _current_source = None
                time.sleep(IDLE_POLL_SECONDS)
                continue
            _current_proc = proc
            _current_source = source
            _mode = "idle"

        try:
            proc.wait()
        except Exception:
            pass

        with _lock:
            if _current_proc is proc:
                _current_proc = None
                _current_source = None


@app.on_event("startup")
def _startup() -> None:
    global _idle_thread_started

    with _lock:
        if _idle_thread_started:
            return
        _idle_thread_started = True

    thread = threading.Thread(target=_idle_loop, daemon=True)
    thread.start()


@app.post("/play")
def play(body: dict[str, Any]) -> dict[str, str]:
    global _mode

    item_number = body.get("item_number")
    file_path = body.get("file_path")

    if item_number:
        item_number_value = str(item_number).strip()
        if not item_number_value:
            return {"status": "no_match", "item_number": item_number_value}

        match = next(
            (
                path
                for path in sorted(glob.glob(os.path.join(VIDEO_DIR, "*")))
                if item_number_value.lower() in os.path.basename(path).lower()
            ),
            None,
        )
        if match is None:
            return {"status": "no_match", "item_number": item_number_value}
        source = match
    else:
        if not file_path:
            raise HTTPException(status_code=400, detail="Missing file_path")
        source = str(file_path)

    with _lock:
        try:
            _start_triggered_playback_locked(source)
        except Exception as exc:
            _trigger_event.clear()
            _mode = "idle"
            _stop_current_process_locked()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "playing", "source": source}


@app.get("/videos")
def list_videos() -> dict:
    files = sorted(glob.glob(os.path.join(VIDEO_DIR, "*.mp4")))
    return {"videos": [os.path.basename(f) for f in files]}


@app.post("/idle/playlist")
def update_idle_playlist(body: dict[str, Any]) -> dict[str, Any]:
    paths = body.get("paths")
    if not isinstance(paths, list):
        raise HTTPException(status_code=400, detail="Missing paths")

    cleaned_paths = [str(path) for path in paths if str(path)]

    with _lock:
        _idle_playlist[:] = cleaned_paths

    return {"status": "ok", "count": len(cleaned_paths)}


@app.post("/stop")
def stop() -> dict[str, str]:
    global _mode

    with _lock:
        _cancel_idle_timer_locked()
        _trigger_event.clear()
        _mode = "idle"
        _stop_current_process_locked()

    return {"status": "idle"}


@app.get("/status")
def status() -> dict[str, Any]:
    with _lock:
        _cleanup_finished_process_locked()
        proc = _current_proc
        source = _current_source
        mode = _mode
        pid = proc.pid if proc is not None and proc.poll() is None else None
        if pid is None and mode == "idle" and source is None:
            source = None

    return {"mode": mode, "source": source, "pid": pid}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
