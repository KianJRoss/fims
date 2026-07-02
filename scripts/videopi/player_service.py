from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import subprocess
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException


VIDEO_DIR = "/media/pi/VIDEOS/videos"
IDLE_RETURN_SECONDS = 60
# Safety-net cap: a triggered clip normally returns to the idle queue the instant
# its mpv process exits (it plays exactly ONCE). This cap only matters if mpv hangs
# and never exits on its own; it's far longer than any real demo clip so it never
# cuts a legitimately-playing video short.
TRIGGERED_MAX_SECONDS = 600
IDLE_POLL_SECONDS = 0.5
# The curated idle playlist (pushed via POST /idle/playlist) is persisted here so
# it survives a service restart / Pi reboot. Without this the idle loop falls back
# to shuffling EVERY file in VIDEO_DIR (the whole ~14k library), not the in-store set.
IDLE_PLAYLIST_FILE = os.path.expanduser("~/.config/fims/idle_playlist.json")
TRANSITION_CACHE_DIR = "/tmp/fims_transitions"
TRANSITION_DURATION = 4  # seconds each brand card is shown
INTERSTITIAL_IMAGE_DIR = "/media/pi/VIDEOS/interstitials"
INTERSTITIAL_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

BRAND_PREFIX_MAP: dict[str, str] = {
    "WC": "WORLD CLASS",
    "RR": "RED RHINO",
    "CE": "CUTTING EDGE",
    "JB": "JAKE'S FIREWORKS",
    "BC": "BLACK CAT",
    "PB": "PYRO BOX",
    "SW": "SUNWING",
    "WT": "WORLD CLASS",
}

app = FastAPI(title="FIMS Video Kiosk Player Service")

_lock = threading.Lock()
_trigger_event = threading.Event()
_current_proc: subprocess.Popen[bytes] | None = None
_current_source: str | None = None
_mode = "idle"
_idle_playlist: list[str] = []
_idle_timer: threading.Timer | None = None
_idle_timer_generation = 0
_triggered_generation = 0
_idle_thread_started = False


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
    env.setdefault("DISPLAY", ":0")
    return env


def _brand_from_filename(filename: str) -> str:
    name = os.path.basename(filename).upper()
    for prefix, brand in BRAND_PREFIX_MAP.items():
        if name.startswith(prefix + "-") or name.startswith(prefix + "_"):
            return brand
    return "FIREWORKS"


def _get_transition_png(brand: str) -> str | None:
    os.makedirs(TRANSITION_CACHE_DIR, exist_ok=True)
    safe = brand.replace(" ", "_").replace("'", "").upper()
    path = os.path.join(TRANSITION_CACHE_DIR, f"{safe}.png")
    if os.path.exists(path):
        return path

    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    font = next((f for f in font_candidates if os.path.exists(f)), None)
    font_opt = f":fontfile={font}" if font else ""
    escaped = brand.replace("'", "\\'").replace(":", "\\:")
    vf = f"drawtext=text='{escaped}'{font_opt}:fontsize=96:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2"

    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:size=1920x1080:rate=1",
         "-frames:v", "1", "-vf", vf, path],
        capture_output=True,
    )
    return path if result.returncode == 0 else None


def _get_no_video_card_png(lines: list[str]) -> str | None:
    os.makedirs(TRANSITION_CACHE_DIR, exist_ok=True)
    joined = "\n".join(lines)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()
    path = os.path.join(TRANSITION_CACHE_DIR, f"card_{digest}.png")
    if os.path.exists(path):
        return path

    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    font = next((f for f in font_candidates if os.path.exists(f)), None)
    font_opt = f":fontfile={font}" if font else ""
    offsets_by_count = {
        1: [0],
        2: [-70, 70],
        3: [-120, 20, 120],
    }
    filters = []
    for index, line in enumerate(lines):
        escaped = line.replace("'", "\\'").replace(":", "\\:")
        fontsize = 96 if index == 0 else 54
        fontcolor = "white" if index == 0 else "0xBBBBBB"
        offset = offsets_by_count[len(lines)][index]
        sign = "+" if offset >= 0 else "-"
        y_expr = f"(h-text_h)/2{sign}{abs(offset)}" if offset else "(h-text_h)/2"
        filters.append(
            f"drawtext=text='{escaped}'{font_opt}:fontsize={fontsize}:"
            f"fontcolor={fontcolor}:x=(w-text_w)/2:y={y_expr}"
        )

    result = subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=black:size=1920x1080:rate=1",
            "-frames:v", "1", "-vf", ",".join(filters), path,
        ],
        capture_output=True,
    )
    return path if result.returncode == 0 else None


def _list_interstitial_images() -> list[str]:
    if not os.path.isdir(INTERSTITIAL_IMAGE_DIR):
        return []
    return [
        path
        for path in sorted(glob.glob(os.path.join(INTERSTITIAL_IMAGE_DIR, "*")))
        if os.path.splitext(path)[1].lower() in INTERSTITIAL_IMAGE_EXTS
    ]


def _spawn_mpv_playlist(playlist_path: str) -> subprocess.Popen[bytes]:
    command = [
        "mpv", "--fs", "--really-quiet", "--no-terminal",
        "--force-window=yes",
        f"--image-display-duration={TRANSITION_DURATION}",
        f"--playlist={playlist_path}",
    ]
    return subprocess.Popen(command, env=_build_env())


def _spawn_mpv(path: str, loop_forever: bool = False) -> subprocess.Popen[bytes]:
    command = ["mpv", "--fs", "--really-quiet", "--no-terminal"]
    if loop_forever:
        command.append("--loop-file=inf")
    command.append(path)
    return subprocess.Popen(command, env=_build_env())


def _spawn_mpv_card(path: str) -> subprocess.Popen[bytes]:
    command = [
        "mpv", "--fs", "--really-quiet", "--no-terminal",
        "--force-window=yes",
        "--image-display-duration=6",
        path,
    ]
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


def _probe_duration(path: str) -> float | None:
    """Best-effort clip length in seconds via ffprobe; None if unknown."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        value = out.stdout.strip()
        return float(value) if value else None
    except Exception:
        return None


def _triggered_watcher(
    proc: subprocess.Popen[bytes], generation: int, duration: float | None
) -> None:
    """Return to the idle queue when a triggered clip finishes — once, no replay.

    The clip is spawned to play exactly once (no --loop-file). We return to idle
    as soon as mpv exits on its own; but mpv on this Pi does not reliably quit at
    end-of-file, so we also return after the clip's known duration elapses. This
    replaces the old fixed IDLE_RETURN_SECONDS timer, so short clips no longer
    loop/replay and long clips are no longer cut off at 60s.
    """
    # _mode is assigned below ("idle"), so it must be declared global or every
    # read of it in this function raises UnboundLocalError and the watcher
    # thread dies before ever returning to the idle queue.
    global _mode

    if duration and duration > 0:
        deadline = time.time() + duration + 3.0
    else:
        deadline = time.time() + TRIGGERED_MAX_SECONDS

    # Return as soon as mpv exits on its own; otherwise fall back to the
    # duration-based deadline (mpv on this Pi doesn't reliably quit at EOF).
    while proc.poll() is None:
        if time.time() >= deadline:
            break
        time.sleep(0.2)

    with _lock:
        # A newer scan replaced this clip, or we've already returned to idle —
        # nothing to do.
        if generation != _triggered_generation:
            return
        if _mode != "triggered":
            return
        _cancel_idle_timer_locked()
        _trigger_event.clear()
        _mode = "idle"
        _stop_current_process_locked()


def _start_triggered_playback_locked(source: str) -> None:
    global _current_proc, _current_source, _mode, _triggered_generation

    _cancel_idle_timer_locked()
    _stop_current_process_locked()
    _trigger_event.set()
    _mode = "triggered"

    # Play the clip ONCE. Returning to the idle queue is driven by the clip
    # actually ending (watched below), not by a fixed timer.
    proc = _spawn_mpv(source, loop_forever=False)
    _current_proc = proc
    _current_source = source

    duration = _probe_duration(source)
    _triggered_generation += 1
    watcher = threading.Thread(
        target=_triggered_watcher,
        args=(proc, _triggered_generation, duration),
        daemon=True,
    )
    watcher.start()


def _start_card_locked(path: str) -> None:
    global _current_proc, _current_source, _mode, _triggered_generation

    _cancel_idle_timer_locked()
    _stop_current_process_locked()
    _trigger_event.set()
    _mode = "triggered"

    proc = _spawn_mpv_card(path)
    _current_proc = proc
    _current_source = path

    _triggered_generation += 1
    watcher = threading.Thread(
        target=_triggered_watcher,
        args=(proc, _triggered_generation, 6.0),
        daemon=True,
    )
    watcher.start()


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

    display_deadline = time.time() + 120
    while time.time() < display_deadline:
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
        wayland_socket = os.path.join(runtime_dir, wayland_display)
        x_socket = "/tmp/.X11-unix/X0"
        if os.path.exists(wayland_socket) or os.path.exists(x_socket):
            break
        time.sleep(2)

    video_deadline = time.time() + 120
    while time.time() < video_deadline:
        if glob.glob(os.path.join(VIDEO_DIR, "*.mp4")):
            break
        time.sleep(2)

    while True:
        if _trigger_event.is_set():
            time.sleep(IDLE_POLL_SECONDS)
            continue

        with _lock:
            playlist = list(_idle_playlist)

        if not playlist:
            files = glob.glob(os.path.join(VIDEO_DIR, "*.mp4"))
            playlist = sorted(files)

        if not playlist:
            time.sleep(IDLE_POLL_SECONDS)
            continue

        random.shuffle(playlist)
        interstitials = _list_interstitial_images()
        expanded: list[str] = []
        if interstitials and len(playlist) > 1:
            # Insert promo images with a random gap so they show up every 5-10
            # videos without ever forming a consecutive image block.
            photo_idx = 0
            photo_interval = random.randint(5, 10)
            videos_since_photo = 0
            for video_path in playlist:
                expanded.append(video_path)
                videos_since_photo += 1
                if photo_idx < len(interstitials) and videos_since_photo >= photo_interval:
                    expanded.append(interstitials[photo_idx])
                    photo_idx = (photo_idx + 1) % len(interstitials)
                    videos_since_photo = 0
                    photo_interval = random.randint(5, 10)
        else:
            expanded = playlist

        playlist_path = "/tmp/fims_idle.m3u"
        try:
            with open(playlist_path, "w") as fh:
                fh.write("\n".join(["#EXTM3U", *expanded]) + "\n")
        except Exception:
            time.sleep(IDLE_POLL_SECONDS)
            continue

        with _lock:
            if _trigger_event.is_set():
                continue
            _cleanup_finished_process_locked()
            try:
                proc = _spawn_mpv_playlist(playlist_path)
            except Exception:
                time.sleep(IDLE_POLL_SECONDS)
                continue
            spawn_time = time.time()
            _current_proc = proc
            _current_source = playlist_path
            _mode = "idle"

        while proc.poll() is None:
            if _trigger_event.is_set():
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                break
            time.sleep(IDLE_POLL_SECONDS)

        with _lock:
            if _current_proc is proc:
                _current_proc = None
                _current_source = None

        if time.time() - spawn_time < 2:
            time.sleep(3)


def _save_idle_playlist(paths: list[str]) -> None:
    try:
        os.makedirs(os.path.dirname(IDLE_PLAYLIST_FILE), exist_ok=True)
        tmp = IDLE_PLAYLIST_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(paths, fh)
        os.replace(tmp, IDLE_PLAYLIST_FILE)
    except Exception:
        pass


def _load_idle_playlist() -> list[str]:
    try:
        with open(IDLE_PLAYLIST_FILE) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return [str(p) for p in data if str(p)]
    except Exception:
        pass
    return []


@app.on_event("startup")
def _startup() -> None:
    global _idle_thread_started

    with _lock:
        if _idle_thread_started:
            return
        _idle_thread_started = True
        # Restore the last curated idle playlist so a restart doesn't revert to
        # shuffling the entire library.
        if not _idle_playlist:
            saved = _load_idle_playlist()
            if saved:
                _idle_playlist[:] = saved

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


@app.post("/no-video")
def no_video(body: dict[str, Any]) -> dict[str, Any]:
    global _mode

    raw_lines = body.get("lines")
    if not isinstance(raw_lines, list):
        raise HTTPException(status_code=400, detail="Missing lines")

    if not 1 <= len(raw_lines) <= 3:
        raise HTTPException(status_code=400, detail="Expected 1-3 non-empty lines")
    if not all(isinstance(line, str) and line.strip() for line in raw_lines):
        raise HTTPException(status_code=400, detail="Expected 1-3 non-empty lines")

    lines = [line.strip() for line in raw_lines]

    path = _get_no_video_card_png(lines)
    if path is None:
        return {"status": "render_failed"}

    with _lock:
        try:
            _start_card_locked(path)
        except Exception as exc:
            _trigger_event.clear()
            _mode = "idle"
            _stop_current_process_locked()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "card", "lines": lines}


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

    _save_idle_playlist(cleaned_paths)
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
