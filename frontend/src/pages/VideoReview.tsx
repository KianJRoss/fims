import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlayCircle, Search, VideoOff } from "lucide-react";

type QueueProduct = {
  id: string;
  name: string;
  item_number: string | null;
  brand_name: string | null;
  category_name: string | null;
  barcode_count: number;
  video_count: number;
  in_store: boolean;
  shot_count: number | null;
  created_at: string;
};

type ProductVideo = {
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

type ProductDetail = QueueProduct & {
  description: string | null;
  notes: string | null;
  category_id: number | null;
  brand_id: number | null;
  duration_seconds: number | null;
  effects: string | null;
  is_active: boolean;
  no_video_confirmed: boolean;
  updated_at: string;
  barcodes: Array<{
    id: number;
    barcode: string;
    barcode_type: string;
    is_primary: boolean;
    notes: string | null;
  }>;
  videos: ProductVideo[];
};

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });

function formatDuration(totalSeconds: number | null) {
  if (totalSeconds === null || Number.isNaN(totalSeconds)) return "Unknown";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function nextQueueId(queue: QueueProduct[], currentId: string | null) {
  if (!currentId || queue.length === 0) return queue[0]?.id ?? null;
  const currentIndex = queue.findIndex((item) => item.id === currentId);
  if (currentIndex < 0) return queue[0]?.id ?? null;
  return queue[currentIndex + 1]?.id ?? null;
}

export default function VideoReview() {
  const queryClient = useQueryClient();
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  const queueQuery = useQuery({
    queryKey: ["video-review-queue"],
    queryFn: async (): Promise<QueueProduct[]> => {
      const { data } = await api.get("/v1/products/", {
        params: {
          no_video: true,
          limit: 1000,
          sort: "recent",
        },
      });
      return data;
    },
  });

  const queue = queueQuery.data ?? [];

  useEffect(() => {
    if (!queue.length) {
      setSelectedProductId(null);
      return;
    }

    if (!selectedProductId || !queue.some((item) => item.id === selectedProductId)) {
      setSelectedProductId(queue[0].id);
    }
  }, [queue, selectedProductId]);

  const selectedProductQuery = useQuery({
    queryKey: ["video-review-product", selectedProductId],
    queryFn: async (): Promise<ProductDetail> => {
      if (!selectedProductId) {
        throw new Error("Missing selected product");
      }
      const { data } = await api.get(`/v1/products/${selectedProductId}`);
      return data;
    },
    enabled: Boolean(selectedProductId),
    refetchInterval: (query) => {
      const videos = (query.state.data?.videos as ProductVideo[] | undefined) ?? [];
      return videos.some((video) => !["done", "error"].includes(video.download_status)) ? 3000 : false;
    },
    refetchOnWindowFocus: false,
  });

  const activeProduct = selectedProductQuery.data;
  const activeVideos = activeProduct?.videos ?? [];
  const reviewCount = queue.length;

  const searchMutation = useMutation({
    mutationFn: async (productId: string) => {
      const { data } = await api.post(`/v1/videos/product/${productId}/search`);
      return data;
    },
    onSuccess: async () => {
      if (selectedProductId) {
        await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
      }
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (payload: { videoId: number; nextProductId: string | null }) => {
      const { data } = await api.patch(`/v1/videos/${payload.videoId}/confirm`, {
        confirmed: true,
        is_primary: true,
      });
      return { data, nextProductId: payload.nextProductId };
    },
    onSuccess: async (_, variables) => {
      if (selectedProductId) {
        await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
      }
      await queryClient.invalidateQueries({ queryKey: ["video-review-queue"] });
      setSelectedProductId(variables.nextProductId);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (videoId: number) => {
      await api.delete(`/v1/videos/${videoId}`);
      return videoId;
    },
    onSuccess: async () => {
      if (selectedProductId) {
        await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
      }
    },
  });

  const noVideoMutation = useMutation({
    mutationFn: async (productId: string) => {
      const { data } = await api.post(`/v1/videos/product/${productId}/no-video`);
      return data;
    },
    onSuccess: async () => {
      if (selectedProductId) {
        await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
      }
      await queryClient.invalidateQueries({ queryKey: ["video-review-queue"] });
      setSelectedProductId((current) => nextQueueId(queue, current));
    },
  });

  const selectedIndex = useMemo(
    () => queue.findIndex((item) => item.id === selectedProductId),
    [queue, selectedProductId]
  );

  const headerSummary = activeProduct ?? queue[selectedIndex] ?? null;

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Video Review</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {reviewCount.toLocaleString()} products need videos
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-400">
              Review the queue, confirm the correct YouTube result, or mark the product as having no video.
            </p>
          </div>
          <button
            onClick={() => selectedProductId && searchMutation.mutate(selectedProductId)}
            disabled={!selectedProductId || searchMutation.isPending}
            className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
          >
            <Search className="h-4 w-4" />
            Search YouTube
          </button>
        </div>
      </div>

      <div className="flex min-h-[calc(100vh-81px)]">
        <aside className="w-64 shrink-0 border-r border-gray-800 bg-gray-900/90">
          <div className="border-b border-gray-800 px-4 py-4">
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Review Queue</div>
          </div>
          <div className="max-h-[calc(100vh-145px)] overflow-auto p-3">
            {queue.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-gray-800 px-4 py-8 text-center text-sm text-gray-500">
                No products need videos right now.
              </div>
            ) : (
              <div className="space-y-2">
                {queue.map((product, index) => {
                  const active = product.id === selectedProductId;
                  return (
                    <button
                      key={product.id}
                      onClick={() => setSelectedProductId(product.id)}
                      className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                        active
                          ? "border-orange-500 bg-orange-500/10"
                          : "border-gray-800 bg-gray-950 hover:border-gray-700 hover:bg-gray-900"
                      }`}
                    >
                      <div className="text-sm font-medium text-gray-50">{product.name}</div>
                      <div className="mt-1 flex items-center justify-between gap-2 text-xs text-gray-500">
                        <span className="truncate">{product.brand_name || "No brand"}</span>
                        <span>#{index + 1}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </aside>

        <main className="flex-1 overflow-auto px-6 py-6">
          {!selectedProductId ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
              Select a product from the queue.
            </div>
          ) : selectedProductQuery.isLoading ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
              Loading product...
            </div>
          ) : headerSummary ? (
            <div className="space-y-6">
              <section className="rounded-3xl border border-gray-800 bg-gray-900 p-5">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <div className="text-3xl font-semibold text-gray-50">{headerSummary.name}</div>
                    <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-400">
                      <span>{headerSummary.item_number || "No item number"}</span>
                      <span>{headerSummary.brand_name || "No brand"}</span>
                      <span>{headerSummary.shot_count != null ? `${headerSummary.shot_count} shots` : "Shot count unknown"}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge label={headerSummary.category_name || "No category"} />
                    <Badge label={headerSummary.in_store ? "In Store" : "Catalog"} tone="border-emerald-500/30 bg-emerald-500/10 text-emerald-200" />
                  </div>
                </div>
              </section>

              <section className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Candidates</div>
                    <div className="mt-1 text-sm text-gray-400">
                      {activeVideos.length} video{activeVideos.length === 1 ? "" : "s"}
                    </div>
                  </div>
                  {selectedProductId && (
                    <button
                      onClick={() => searchMutation.mutate(selectedProductId)}
                      disabled={searchMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-900 px-4 py-2.5 text-sm text-gray-200 transition hover:border-gray-700 hover:bg-gray-800 disabled:cursor-not-allowed disabled:text-gray-500"
                    >
                      <PlayCircle className="h-4 w-4" />
                      Search YouTube
                    </button>
                  )}
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  {activeVideos.map((video) => (
                    <article key={video.id} className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
                      <div className="aspect-[16/9] bg-gray-950">
                        {video.youtube_id ? (
                          <img
                            src={video.thumbnail_url || `https://img.youtube.com/vi/${video.youtube_id}/hqdefault.jpg`}
                            alt={video.title || "Video thumbnail"}
                            className="h-full w-full object-cover"
                          />
                        ) : (
                          <div className="flex h-full items-center justify-center text-sm text-gray-500">No thumbnail</div>
                        )}
                      </div>

                      <div className="space-y-3 p-4">
                        <h3
                          className="text-sm font-semibold text-gray-50"
                          style={{
                            display: "-webkit-box",
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: "vertical",
                            overflow: "hidden",
                          }}
                        >
                          {video.title || "Untitled video"}
                        </h3>
                        <div className="flex items-center justify-between text-xs text-gray-500">
                          <span>{video.original_filename || "Unknown source"}</span>
                          <span>{formatDuration(video.duration_seconds)}</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() =>
                              confirmMutation.mutate({
                                videoId: video.id,
                                nextProductId: nextQueueId(queue, selectedProductId),
                              })
                            }
                            disabled={confirmMutation.isPending}
                            className="rounded-2xl bg-emerald-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                          >
                            This is it
                          </button>
                          <button
                            onClick={() => deleteMutation.mutate(video.id)}
                            disabled={deleteMutation.isPending}
                            className="rounded-2xl border border-gray-700 bg-gray-950 px-3 py-2 text-sm font-semibold text-gray-300 transition hover:border-gray-600 hover:bg-gray-900 disabled:cursor-not-allowed disabled:text-gray-500"
                          >
                            Not this one
                          </button>
                        </div>
                        <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.2em] text-gray-500">
                          <span className="rounded-full border border-gray-700 px-2 py-1">{video.download_status}</span>
                          <span>{video.confirmed ? "Confirmed" : "Unconfirmed"}</span>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>

                {activeVideos.length === 0 && (
                  <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-8 text-center text-sm text-gray-500">
                    No candidates yet. Search YouTube to queue results.
                  </div>
                )}
              </section>

              <section className="rounded-3xl border border-red-500/40 bg-red-500/5 p-5">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div className="text-sm font-semibold text-red-200">No video exists</div>
                    <div className="mt-1 text-sm text-red-100/70">
                      Mark the product as having no confirmed video and advance to the next item in the queue.
                    </div>
                  </div>
                  <button
                    onClick={() => selectedProductId && noVideoMutation.mutate(selectedProductId)}
                    disabled={noVideoMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-2xl border border-red-400/60 px-4 py-3 text-sm font-semibold text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:text-red-300/50"
                  >
                    <VideoOff className="h-4 w-4" />
                    No video exists
                  </button>
                </div>
              </section>
            </div>
          ) : (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
              Could not load the selected product.
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function Badge({ label, tone = "border-gray-700 bg-gray-950 text-gray-300" }: { label: string; tone?: string }) {
  return <span className={`rounded-full border px-3 py-1 text-xs ${tone}`}>{label}</span>;
}
