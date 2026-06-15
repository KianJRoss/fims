import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Power, Search, Tv2 } from "lucide-react";

import { api } from "../api/client";

type VideoLibraryResponse = {
  videos: string[];
  count: number;
  error?: string;
};

type VideoStatusResponse = Record<string, unknown> | null;

const VIDEO_ROOT = "/media/pi/VIDEOS/videos";

function getFilename(value: string | null | undefined) {
  if (!value) {
    return null;
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }

  return trimmed.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? trimmed;
}

function toDisplayName(filename: string) {
  return filename.replace(/^\d+[-\s]*/, "").replace(/\.mp4$/i, "").trim();
}

function extractStatusFilename(status: VideoStatusResponse) {
  if (!status || typeof status !== "object") {
    return null;
  }

  const candidateKeys = [
    "file_path",
    "filename",
    "file_name",
    "current_file",
    "current_filename",
    "source",
    "path",
    "url",
  ] as const;

  for (const key of candidateKeys) {
    const value = status[key];
    if (typeof value !== "string") {
      continue;
    }

    const trimmed = value.trim();
    if (!trimmed) {
      continue;
    }

    const normalized = trimmed.toLowerCase();
    if (["idle", "stopped", "stop", "off", "standby", "not_playing"].includes(normalized)) {
      return null;
    }

    return getFilename(trimmed);
  }

  return null;
}

function isPlayingStatus(status: VideoStatusResponse, filename: string | null) {
  if (!status || typeof status !== "object") {
    return Boolean(filename);
  }

  const statusValue = ["status", "state", "mode"]
    .map((key) => status[key])
    .find((value) => typeof value === "string") as string | undefined;

  if (statusValue) {
    const normalized = statusValue.trim().toLowerCase();
    if (["idle", "stopped", "stop", "off", "standby", "not_playing"].includes(normalized)) {
      return false;
    }
    if (["playing", "active", "running", "on"].includes(normalized)) {
      return true;
    }
  }

  const playingFlag =
    typeof status.playing === "boolean"
      ? status.playing
      : typeof status.is_playing === "boolean"
        ? status.is_playing
        : typeof status.active === "boolean"
          ? status.active
          : false;

  return playingFlag || Boolean(filename);
}

export default function VideoRemote() {
  const [search, setSearch] = useState("");
  const [optimisticPlayback, setOptimisticPlayback] = useState<{ filename: string; expiresAt: number } | null>(null);

  const videosQuery = useQuery({
    queryKey: ["video-remote-videos"],
    queryFn: async (): Promise<VideoLibraryResponse> => (await api.get("/v1/video-library/player/videos")).data,
  });

  const statusQuery = useQuery({
    queryKey: ["video-remote-status"],
    queryFn: async (): Promise<VideoStatusResponse> => (await api.get("/v1/video-library/player/status")).data,
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
  });

  const statusData = statusQuery.data;
  const statusFilename = statusData ? extractStatusFilename(statusData) : null;
  const activeFilename = statusFilename ?? optimisticPlayback?.filename ?? null;
  const playing = (statusData ? isPlayingStatus(statusData, activeFilename) : false) || Boolean(optimisticPlayback);
  const statusLabel = playing ? "playing" : "idle";

  useEffect(() => {
    if (statusFilename && statusData && isPlayingStatus(statusData, statusFilename)) {
      setOptimisticPlayback({ filename: statusFilename, expiresAt: Date.now() + 10_000 });
    }
  }, [statusFilename, statusData]);

  useEffect(() => {
    if (!optimisticPlayback) {
      return;
    }

    const delay = Math.max(0, optimisticPlayback.expiresAt - Date.now());
    const timer = window.setTimeout(() => setOptimisticPlayback(null), delay);
    return () => window.clearTimeout(timer);
  }, [optimisticPlayback]);

  const playMutation = useMutation({
    mutationFn: async (filename: string) => {
      const { data } = await api.post("/v1/video-library/player/play", {
        file_path: `${VIDEO_ROOT}/${filename}`,
      });
      return { data, filename };
    },
    onSuccess: async (_result, filename) => {
      setOptimisticPlayback({ filename, expiresAt: Date.now() + 10_000 });
      await statusQuery.refetch();
    },
  });

  const stopMutation = useMutation({
    mutationFn: async () => (await api.post("/v1/video-library/player/stop")).data,
    onSuccess: async () => {
      setOptimisticPlayback(null);
      await statusQuery.refetch();
    },
  });

  const videos = videosQuery.data?.videos ?? [];
  const filteredVideos = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) {
      return videos;
    }

    return videos.filter((filename) => {
      const displayName = toDisplayName(filename).toLowerCase();
      return filename.toLowerCase().includes(term) || displayName.includes(term);
    });
  }, [search, videos]);

  const videoCount = videosQuery.data?.count ?? videos.length;

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-5 backdrop-blur">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.35em] text-orange-300/80">
              <Tv2 className="h-4 w-4" />
              Video Remote
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Video Remote</h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-400">
              Browse the Pi video library, filter by filename, and start or stop playback from FIMS.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium ${
                playing ? "border-orange-500/40 bg-orange-500/10 text-orange-200" : "border-gray-700 bg-gray-900 text-gray-300"
              }`}
            >
              <span className={`h-2.5 w-2.5 rounded-full ${playing ? "bg-orange-400" : "bg-gray-500"}`} />
              <span className="uppercase tracking-[0.25em]">{statusLabel}</span>
              {playing && activeFilename ? <span className="max-w-[18rem] truncate text-gray-300">- {activeFilename}</span> : null}
            </div>

            <button
              onClick={() => stopMutation.mutate()}
              disabled={stopMutation.isPending}
              className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-900 px-4 py-3 text-sm font-semibold text-gray-100 transition hover:border-gray-700 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {stopMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
              Return to Idle
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-6 px-6 py-6">
        <section className="rounded-3xl border border-gray-800 bg-gray-900 p-4 shadow-2xl shadow-black/20">
          <label className="flex items-center gap-3 rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3">
            <Search className="h-4 w-4 text-gray-500" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by filename"
              className="w-full bg-transparent text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none"
            />
          </label>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs uppercase tracking-[0.22em] text-gray-500">
            <span>{videoCount} videos</span>
            <span>{filteredVideos.length} shown</span>
            {videosQuery.data?.error ? <span className="text-red-300">{videosQuery.data.error}</span> : null}
          </div>
        </section>

        <section>
          {videosQuery.isLoading ? (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 px-6 py-16 text-center text-sm text-gray-500">
              <Loader2 className="mx-auto mb-3 h-5 w-5 animate-spin text-orange-400" />
              Loading video list...
            </div>
          ) : filteredVideos.length === 0 ? (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 px-6 py-16 text-center text-sm text-gray-500">
              {search.trim() ? "No videos match the current search." : "No videos returned from the video Pi."}
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
              {filteredVideos.map((filename) => {
                const active = filename === activeFilename;

                return (
                  <button
                    key={filename}
                    onClick={() => playMutation.mutate(filename)}
                    disabled={playMutation.isPending}
                    className={`group rounded-3xl border p-4 text-left transition ${
                      active
                        ? "border-orange-500 bg-orange-500/10 shadow-lg shadow-orange-500/10"
                        : "border-gray-800 bg-gray-900 hover:border-gray-700 hover:bg-gray-800"
                    } disabled:cursor-not-allowed disabled:opacity-80`}
                  >
                    <div className="flex min-h-28 flex-col justify-between gap-4">
                      <div>
                        <div className="text-lg font-semibold tracking-tight text-gray-50 transition group-hover:text-orange-100">
                          {toDisplayName(filename)}
                        </div>
                        <div className="mt-2 break-all text-sm text-gray-500">{filename}</div>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span
                          className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.22em] ${
                            active ? "border-orange-500/50 bg-orange-500/15 text-orange-200" : "border-gray-700 bg-gray-950 text-gray-400"
                          }`}
                        >
                          {active ? "Active" : "Ready"}
                        </span>
                        {playMutation.isPending && active ? <Loader2 className="h-4 w-4 animate-spin text-orange-400" /> : null}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
