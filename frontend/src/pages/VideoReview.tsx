import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type Product = {
  id: string;
  name: string;
  item_number: string | null;
};

type Video = {
  id: number;
  product_id: string;
  file_path: string;
  source: string;
  url: string | null;
  youtube_id: string | null;
  title: string | null;
  thumbnail_url: string | null;
  search_query: string | null;
  confirmed: boolean;
  download_status: string;
  original_filename: string | null;
  duration_seconds: number | null;
  is_primary: boolean;
  uploaded_at: string;
  downloaded: boolean;
};

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });

function formatDuration(totalSeconds: number | null) {
  if (totalSeconds === null || Number.isNaN(totalSeconds)) return "";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function resolveThumbnail(video: Video) {
  return video.thumbnail_url || (video.youtube_id ? `https://img.youtube.com/vi/${video.youtube_id}/hqdefault.jpg` : "");
}

function badgeForVideo(video: Video) {
  if (video.confirmed && video.download_status === "done") {
    return { label: "Downloaded", className: "bg-emerald-500/90 text-white" };
  }

  if (video.confirmed && ["queued", "downloading", "pending"].includes(video.download_status)) {
    return { label: "Downloading...", className: "bg-amber-400/90 text-gray-950" };
  }

  if (video.confirmed && video.download_status === "error") {
    return { label: "Error", className: "bg-rose-500/90 text-white" };
  }

  return { label: "Unreviewed", className: "bg-slate-500/90 text-white" };
}

export default function VideoReview() {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedTerm, setDebouncedTerm] = useState("");
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [showResults, setShowResults] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedTerm(searchTerm.trim());
    }, 300);

    return () => window.clearTimeout(timer);
  }, [searchTerm]);

  const searchQuery = useQuery({
    queryKey: ["video-review-products", debouncedTerm],
    queryFn: async (): Promise<Product[]> => {
      const { data } = await api.get("/v1/products/", {
        params: { q: debouncedTerm, limit: 10 },
      });
      return data;
    },
    enabled: debouncedTerm.length > 0,
  });

  useEffect(() => {
    if (!searchQuery.data?.length) return;
    if (searchTerm.trim().length === 0) return;
    setShowResults(true);
  }, [searchQuery.data, searchTerm]);

  const videosQuery = useQuery({
    queryKey: ["videos", selectedProduct?.id],
    queryFn: async (): Promise<Video[]> => {
      if (!selectedProduct) {
        throw new Error("Missing selected product");
      }
      const { data } = await api.get(`/v1/videos/product/${selectedProduct.id}`);
      return data;
    },
    enabled: Boolean(selectedProduct),
    refetchInterval: (query) => {
      const items = (query.state.data as Video[] | undefined) ?? [];
      return items.some((video) => !["done", "error"].includes(video.download_status)) ? 5000 : false;
    },
  });

  const searchVideosMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProduct) throw new Error("Missing selected product");
      const { data } = await api.post(`/v1/videos/product/${selectedProduct.id}/search`);
      return data;
    },
    onSuccess: async () => {
      if (selectedProduct) {
        await queryClient.invalidateQueries({ queryKey: ["videos", selectedProduct.id] });
      }
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (payload: { videoId: number; body: { confirmed?: boolean; is_primary?: boolean } }) => {
      const { data } = await api.patch(`/v1/videos/${payload.videoId}/confirm`, payload.body);
      return data as Video;
    },
    onSuccess: async () => {
      if (selectedProduct) {
        await queryClient.invalidateQueries({ queryKey: ["videos", selectedProduct.id] });
      }
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (videoId: number) => {
      await api.delete(`/v1/videos/${videoId}`);
      return videoId;
    },
    onSuccess: async () => {
      if (selectedProduct) {
        await queryClient.invalidateQueries({ queryKey: ["videos", selectedProduct.id] });
      }
    },
  });

  const videos = videosQuery.data ?? [];
  const searchResults = searchQuery.data ?? [];

  const activeLabel = useMemo(() => {
    if (!selectedProduct) return "Select a product to review videos";
    return `${selectedProduct.name}${selectedProduct.item_number ? ` - ${selectedProduct.item_number}` : ""}`;
  }, [selectedProduct]);

  return (
    <div className="min-h-full bg-[radial-gradient(circle_at_top_left,_rgba(249,115,22,0.18),_transparent_26%),radial-gradient(circle_at_top_right,_rgba(59,130,246,0.12),_transparent_30%),linear-gradient(180deg,_#0b1120_0%,_#020617_100%)] text-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-6 lg:px-8">
        <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-5 shadow-2xl shadow-black/20 backdrop-blur">
          <div className="flex flex-col gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Video Review</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Search, confirm, and download product videos</h1>
              <p className="mt-2 max-w-3xl text-sm text-slate-400">
                Find a product, queue video searches, then confirm or reject each result while downloads run in the background.
              </p>
            </div>

            <div className="relative">
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">
                Product search
              </label>
              <input
                value={searchTerm}
                onChange={(event) => {
                  setSearchTerm(event.target.value);
                  setShowResults(true);
                }}
                onFocus={() => setShowResults(true)}
                placeholder="Search by product name or item number"
                className="w-full rounded-2xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-600 focus:border-orange-500 focus:ring-1 focus:ring-orange-500/60"
              />

              {showResults && debouncedTerm && (
                <div className="absolute z-20 mt-2 w-full overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl shadow-black/30">
                  {searchQuery.isLoading ? (
                    <div className="px-4 py-3 text-sm text-slate-400">Searching...</div>
                  ) : searchResults.length === 0 ? (
                    <div className="px-4 py-3 text-sm text-slate-400">No matching products</div>
                  ) : (
                    searchResults.map((product) => (
                      <button
                        key={product.id}
                        onClick={() => {
                          setSelectedProduct(product);
                          setSearchTerm(`${product.name}${product.item_number ? ` ${product.item_number}` : ""}`);
                          setShowResults(false);
                        }}
                        className="flex w-full items-center justify-between gap-3 border-b border-slate-800 px-4 py-3 text-left transition last:border-b-0 hover:bg-slate-900"
                      >
                        <div>
                          <div className="font-medium text-white">{product.name}</div>
                          <div className="text-xs text-slate-500">{product.item_number || "No item number"}</div>
                        </div>
                        <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 text-xs text-orange-200">
                          Select
                        </span>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/60 p-5 shadow-2xl shadow-black/20">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Selected product</p>
              <h2 className="mt-2 text-2xl font-semibold text-white">{activeLabel}</h2>
            </div>
            <button
              onClick={() => searchVideosMutation.mutate()}
              disabled={!selectedProduct || searchVideosMutation.isPending}
              className="rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {searchVideosMutation.isPending ? "Searching..." : "Search for Videos"}
            </button>
          </div>

          {!selectedProduct ? (
            <div className="mt-6 rounded-2xl border border-dashed border-slate-700 px-4 py-12 text-center text-sm text-slate-500">
              Choose a product above to review its videos.
            </div>
          ) : (
            <>
              <div className="mt-6 flex items-center justify-between">
                <div className="text-sm text-slate-400">
                  {videosQuery.isFetching ? "Refreshing video list..." : `${videos.length} video${videos.length === 1 ? "" : "s"}`}
                </div>
                <div className="text-xs uppercase tracking-[0.25em] text-slate-500">
                  {videos.some((video) => !["done", "error"].includes(video.download_status))
                    ? "Auto-refresh enabled"
                    : "Idle"}
                </div>
              </div>

              <div className="mt-5 grid gap-4 sm:grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
                {videos.map((video) => {
                  const badge = badgeForVideo(video);
                  const thumbnail = resolveThumbnail(video);

                  return (
                    <article key={video.id} className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80 shadow-lg shadow-black/20">
                      <div className="relative aspect-[16/10] bg-slate-900">
                        {thumbnail ? (
                          <img src={thumbnail} alt={video.title || "Video thumbnail"} className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full items-center justify-center text-sm text-slate-500">No thumbnail</div>
                        )}
                        <div className={`absolute right-3 top-3 rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] ${badge.className}`}>
                          {badge.label}
                        </div>
                      </div>

                      <div className="space-y-4 p-4">
                        <div className="space-y-2">
                          <h3
                            className="text-base font-semibold text-white"
                            style={{
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                            }}
                          >
                            {video.title || "Untitled video"}
                          </h3>
                          <div className="flex items-center justify-between text-xs text-slate-500">
                            <span>{video.original_filename || video.youtube_id || "Unknown source"}</span>
                            <span>{formatDuration(video.duration_seconds)}</span>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => confirmMutation.mutate({ videoId: video.id, body: { confirmed: true } })}
                            disabled={video.confirmed || confirmMutation.isPending}
                            className="rounded-xl bg-emerald-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => {
                              if (!window.confirm("Reject and delete this video?")) return;
                              deleteMutation.mutate(video.id);
                            }}
                            disabled={deleteMutation.isPending}
                            className="rounded-xl bg-rose-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-rose-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                          >
                            Reject
                          </button>
                          {video.downloaded && (
                            <button
                              onClick={() => confirmMutation.mutate({ videoId: video.id, body: { confirmed: true, is_primary: true } })}
                              disabled={confirmMutation.isPending}
                              className="rounded-xl border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-sm font-semibold text-amber-200 transition hover:bg-amber-400/20 disabled:cursor-not-allowed disabled:text-slate-500"
                            >
                              Star Set Primary
                            </button>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>

              {!videos.length && (
                <div className="mt-6 rounded-2xl border border-dashed border-slate-700 px-4 py-10 text-center text-sm text-slate-500">
                  No videos found for this product yet.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
