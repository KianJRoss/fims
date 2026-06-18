import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Barcode, Loader2, PlayCircle, Power, Repeat, Search, Tv2, VideoOff } from "lucide-react";

import ProductImage from "../components/ProductImage";
import { useScannerStream } from "../hooks/useScannerStream";

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });

type View = "review" | "remote";

const VIEW_TABS: { id: View; label: string; icon: typeof Search }[] = [
  { id: "review", label: "Review Queue", icon: Search },
  { id: "remote", label: "Remote", icon: Tv2 },
];

export default function VideoReview() {
  const [view, setView] = useState<View>("review");

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Videos</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {view === "review" ? "Video Review" : "Video Remote"}
            </h1>
          </div>
          <div className="inline-flex items-center rounded-2xl border border-gray-800 bg-gray-900 p-1">
            {VIEW_TABS.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setView(tab.id)}
                  className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-semibold transition ${
                    view === tab.id ? "bg-orange-500 text-gray-950" : "text-gray-400 hover:text-gray-100"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {view === "review" && <ReviewQueueView />}
      {view === "remote" && <RemoteView />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Review Queue view — formerly the whole Videos page
// ─────────────────────────────────────────────────────────────────────────

type QueueProduct = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
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

function ReviewQueueView() {
  const queryClient = useQueryClient();
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  const queueQuery = useQuery({
    queryKey: ["video-review-queue"],
    queryFn: async (): Promise<QueueProduct[]> => {
      const { data } = await api.get("/v1/products/", {
        params: { no_video: true, limit: 1000, sort: "recent" },
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
    queryFn: async (): Promise<ProductDetail> => (await api.get(`/v1/products/${selectedProductId}`)).data,
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
    mutationFn: async (productId: string) => (await api.post(`/v1/videos/product/${productId}/search`)).data,
    onSuccess: async () => {
      if (selectedProductId) await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
    },
  });

  const confirmMutation = useMutation({
    mutationFn: async (payload: { videoId: number; nextProductId: string | null }) => {
      const { data } = await api.patch(`/v1/videos/${payload.videoId}/confirm`, { confirmed: true, is_primary: true });
      return { data, nextProductId: payload.nextProductId };
    },
    onSuccess: async (_, variables) => {
      if (selectedProductId) await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
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
      if (selectedProductId) await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
    },
  });

  const noVideoMutation = useMutation({
    mutationFn: async (productId: string) => (await api.post(`/v1/videos/product/${productId}/no-video`)).data,
    onSuccess: async () => {
      if (selectedProductId) await queryClient.invalidateQueries({ queryKey: ["video-review-product", selectedProductId] });
      await queryClient.invalidateQueries({ queryKey: ["video-review-queue"] });
      setSelectedProductId((current) => nextQueueId(queue, current));
    },
  });

  const selectedIndex = useMemo(() => queue.findIndex((item) => item.id === selectedProductId), [queue, selectedProductId]);
  const headerSummary = activeProduct ?? queue[selectedIndex] ?? null;

  return (
    <div className="flex min-h-[calc(100vh-81px)] flex-col lg:flex-row">
      <aside className="w-full shrink-0 border-b border-gray-800 bg-gray-900/90 lg:w-64 lg:border-b-0 lg:border-r">
        <div className="border-b border-gray-800 px-4 py-4">
          <div className="text-xs uppercase tracking-[0.25em] text-gray-500">{reviewCount.toLocaleString()} products need videos</div>
        </div>
        <div className="max-h-72 overflow-auto p-3 lg:max-h-[calc(100vh-145px)]">
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
                      active ? "border-orange-500 bg-orange-500/10" : "border-gray-800 bg-gray-950 hover:border-gray-700 hover:bg-gray-900"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <ProductImage imageUrl={product.image_url} name={product.name} size="xs" />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-gray-50 truncate">{product.name}</div>
                        <div className="mt-1 flex items-center justify-between gap-2 text-xs text-gray-500">
                          <span className="truncate">{product.brand_name || "No brand"}</span>
                          <span>#{index + 1}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </aside>

      <main className="flex-1 overflow-auto px-4 py-6 sm:px-6">
        <div className="mb-4 flex justify-end">
          <button
            onClick={() => selectedProductId && searchMutation.mutate(selectedProductId)}
            disabled={!selectedProductId || searchMutation.isPending}
            className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
          >
            <Search className="h-4 w-4" />
            Search YouTube
          </button>
        </div>

        {!selectedProductId ? (
          <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">Select a product from the queue.</div>
        ) : selectedProductQuery.isLoading ? (
          <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">Loading product...</div>
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
                  <div className="mt-1 text-sm text-gray-400">{activeVideos.length} video{activeVideos.length === 1 ? "" : "s"}</div>
                </div>
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
                        style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
                      >
                        {video.title || "Untitled video"}
                      </h3>
                      <div className="flex items-center justify-between text-xs text-gray-500">
                        <span>{video.original_filename || "Unknown source"}</span>
                        <span>{formatDuration(video.duration_seconds)}</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => confirmMutation.mutate({ videoId: video.id, nextProductId: nextQueueId(queue, selectedProductId) })}
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
          <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">Could not load the selected product.</div>
        )}
      </main>
    </div>
  );
}

function Badge({ label, tone = "border-gray-700 bg-gray-950 text-gray-300" }: { label: string; tone?: string }) {
  return <span className={`rounded-full border px-3 py-1 text-xs ${tone}`}>{label}</span>;
}

// ─────────────────────────────────────────────────────────────────────────
// Remote view — play/stop by PRODUCT (not raw filename), product-search driven
// to avoid ever rendering the full ~13,500-file video library at once.
// ─────────────────────────────────────────────────────────────────────────

type RemoteProductResult = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand_name: string | null;
  in_store: boolean;
};

type PlayResult =
  | { status: "ok"; product: RemoteProductResult }
  | { status: "no_match"; product: RemoteProductResult }
  | { status: "not_configured" };

type VideoStatusResponse = Record<string, unknown> | null;

type RemoteBrand = { id: number; name: string };

type IdleFilterResult = { status: string; matched_products?: number; video_count?: number };

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return target.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
}

function getFilename(value: string | null | undefined) {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.replace(/\\/g, "/").split("/").filter(Boolean).pop() ?? trimmed;
}

function extractStatusFilename(status: VideoStatusResponse) {
  if (!status || typeof status !== "object") return null;
  const candidateKeys = ["file_path", "filename", "file_name", "current_file", "current_filename", "source", "path", "url"] as const;
  for (const key of candidateKeys) {
    const value = status[key];
    if (typeof value !== "string") continue;
    const trimmed = value.trim();
    if (!trimmed) continue;
    const normalized = trimmed.toLowerCase();
    if (["idle", "stopped", "stop", "off", "standby", "not_playing"].includes(normalized)) return null;
    return getFilename(trimmed);
  }
  return null;
}

function isPlayingStatus(status: VideoStatusResponse, filename: string | null) {
  if (!status || typeof status !== "object") return Boolean(filename);
  const statusValue = ["status", "state", "mode"].map((key) => status[key]).find((value) => typeof value === "string") as string | undefined;
  if (statusValue) {
    const normalized = statusValue.trim().toLowerCase();
    if (["idle", "stopped", "stop", "off", "standby", "not_playing"].includes(normalized)) return false;
    if (["playing", "active", "running", "on"].includes(normalized)) return true;
  }
  const playingFlag =
    typeof status.playing === "boolean" ? status.playing : typeof status.is_playing === "boolean" ? status.is_playing : typeof status.active === "boolean" ? status.active : false;
  return playingFlag || Boolean(filename);
}

function RemoteView() {
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<RemoteProductResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [lastPlayed, setLastPlayed] = useState<RemoteProductResult | null>(null);
  const [playError, setPlayError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [filterBrandIds, setFilterBrandIds] = useState<number[]>([]);
  const [filterCategory, setFilterCategory] = useState("");
  const [filterInStoreOnly, setFilterInStoreOnly] = useState(true);
  const [loopInfo, setLoopInfo] = useState<IdleFilterResult | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const searchTimerRef = useRef<number | null>(null);
  const bufferRef = useRef("");
  const bufferTimerRef = useRef<number | null>(null);

  const statusQuery = useQuery({
    queryKey: ["video-remote-status"],
    queryFn: async (): Promise<VideoStatusResponse> => (await api.get("/v1/video-library/player/status")).data,
    refetchInterval: 3000,
    refetchOnWindowFocus: false,
  });

  const statusData = statusQuery.data;
  const statusFilename = statusData ? extractStatusFilename(statusData) : null;
  const playing = statusData ? isPlayingStatus(statusData, statusFilename) : false;

  const brandsQuery = useQuery({
    queryKey: ["brands", "video-remote"],
    queryFn: async (): Promise<RemoteBrand[]> => (await api.get("/v1/brands/")).data,
  });

  const categoriesQuery = useQuery({
    queryKey: ["product-categories"],
    queryFn: async (): Promise<string[]> => (await api.get("/v1/products/categories")).data,
  });

  // Quick-access list: in-store products (small, fast, already paginated by the API)
  const inStoreQuery = useQuery({
    queryKey: ["video-remote-in-store"],
    queryFn: async (): Promise<RemoteProductResult[]> =>
      (await api.get("/v1/products/", { params: { in_store: true, limit: 24, sort: "recent" } })).data,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    if (search.trim().length < 2) { setResults([]); return; }

    searchTimerRef.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await api.get("/v1/products/", { params: { q: search.trim(), limit: 12 } });
        setResults(Array.isArray(data) ? data : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => { if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current); };
  }, [search]);

  const playMutation = useMutation({
    mutationFn: async (product: RemoteProductResult): Promise<PlayResult> => {
      const { data } = await api.post("/v1/video-library/player/play", { product_id: product.id });
      if (data?.status === "no_match") return { status: "no_match", product };
      return { status: "ok", product };
    },
    onSuccess: async (result) => {
      if (result.status === "no_match") {
        setPlayError(`No video found for "${result.product.name}".`);
        setLastPlayed(null);
      } else if (result.status === "ok") {
        setPlayError(null);
        setLastPlayed(result.product);
      }
      await statusQuery.refetch();
    },
    onError: () => setPlayError("Could not reach the video player."),
  });

  const stopMutation = useMutation({
    mutationFn: async () => (await api.post("/v1/video-library/player/stop")).data,
    onSuccess: async () => {
      setLastPlayed(null);
      await statusQuery.refetch();
    },
  });

  const loopFilterMutation = useMutation({
    mutationFn: async (): Promise<IdleFilterResult> => {
      const { data } = await api.post("/v1/video-library/player/idle/filter", {
        brand_id: filterBrandIds,
        category: filterCategory || null,
        in_store: filterInStoreOnly ? true : null,
      });
      return data;
    },
    onSuccess: (data) => setLoopInfo(data),
  });

  // Scan a barcode anywhere on this page -> resolve to a product -> override and play immediately,
  // same "scan interrupts the loop" behavior as the old kiosk's barcode-polling play_loop().
  const scanPlayMutation = useMutation({
    mutationFn: async (barcode: string) => {
      const { data: matches } = await api.get(`/v1/products/lookup/barcode/${encodeURIComponent(barcode)}`);
      const match = Array.isArray(matches) ? matches[0] : null;
      if (!match) return { status: "not_found" as const, barcode };
      const product: RemoteProductResult = {
        id: match.id,
        name: match.name,
        item_number: match.item_number,
        image_url: null,
        brand_name: null,
        in_store: true,
      };
      const { data } = await api.post("/v1/video-library/player/play", { product_id: product.id });
      if (data?.status === "no_match") return { status: "no_match" as const, product };
      return { status: "ok" as const, product };
    },
    onSuccess: async (result) => {
      if (result.status === "not_found") {
        setScanMessage(`Barcode ${result.barcode} isn't in the catalog.`);
      } else if (result.status === "no_match") {
        setScanMessage(`No video found for "${result.product.name}".`);
        setLastPlayed(null);
      } else {
        setScanMessage(null);
        setLastPlayed(result.product);
      }
      await statusQuery.refetch();
    },
    onError: () => setScanMessage("Could not look up that barcode."),
  });

  const flushScanBuffer = useCallback(() => {
    if (bufferTimerRef.current !== null) { window.clearTimeout(bufferTimerRef.current); bufferTimerRef.current = null; }
    const barcode = bufferRef.current.trim();
    bufferRef.current = "";
    if (barcode.length < 6) return;
    scanPlayMutation.mutate(barcode);
  }, [scanPlayMutation]);

  useScannerStream((barcode) => scanPlayMutation.mutate(barcode));

  // Keyboard-wedge barcode scanners just type characters fast then Enter, same as Inventory's listener
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.key === "Enter") { event.preventDefault(); flushScanBuffer(); return; }
      if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
      bufferRef.current += event.key;
      if (bufferTimerRef.current !== null) window.clearTimeout(bufferTimerRef.current);
      bufferTimerRef.current = window.setTimeout(flushScanBuffer, 100);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (bufferTimerRef.current !== null) window.clearTimeout(bufferTimerRef.current);
    };
  }, [flushScanBuffer]);

  const showResults = search.trim().length >= 2;
  const listToShow = showResults ? results : inStoreQuery.data ?? [];

  return (
    <div className="space-y-6 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium ${
            playing ? "border-orange-500/40 bg-orange-500/10 text-orange-200" : "border-gray-700 bg-gray-900 text-gray-300"
          }`}
        >
          <span className={`h-2.5 w-2.5 rounded-full ${playing ? "bg-orange-400" : "bg-gray-500"}`} />
          <span className="uppercase tracking-[0.25em]">{playing ? "playing" : "idle"}</span>
          {playing && lastPlayed ? <span className="max-w-[18rem] truncate text-gray-300">- {lastPlayed.name}</span> : null}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowFilters((cur) => !cur)}
            className={`inline-flex items-center gap-2 rounded-2xl border px-4 py-3 text-sm font-semibold transition ${
              showFilters ? "border-orange-500/50 bg-orange-500/10 text-orange-200" : "border-gray-800 bg-gray-900 text-gray-100 hover:border-orange-500/50 hover:bg-gray-800"
            }`}
          >
            <Repeat className="h-4 w-4" />
            Loop Settings
          </button>
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

      {scanMessage && (
        <div className="flex items-center gap-2 rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          <Barcode className="h-4 w-4 shrink-0" />
          {scanMessage}
        </div>
      )}

      {showFilters && (
        <section className="rounded-3xl border border-gray-800 bg-gray-900 p-5 space-y-4">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-gray-400">
            <Repeat className="h-3.5 w-3.5" />
            Idle loop — choose what plays on repeat
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Brands</div>
              <div className="max-h-40 overflow-y-auto space-y-1 pr-1 rounded-2xl border border-gray-800 bg-gray-950 p-2">
                {(brandsQuery.data ?? []).map((brand) => {
                  const checked = filterBrandIds.includes(brand.id);
                  return (
                    <label
                      key={brand.id}
                      className={`flex cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-1.5 text-xs transition ${
                        checked ? "border-orange-500/60 bg-orange-500/10 text-orange-100" : "border-gray-800 bg-gray-950 text-gray-400 hover:border-gray-700"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setFilterBrandIds((prev) => (checked ? prev.filter((id) => id !== brand.id) : [...prev, brand.id]))
                        }
                        className="accent-orange-500"
                      />
                      <span className="truncate">{brand.name}</span>
                    </label>
                  );
                })}
              </div>
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.2em] text-gray-500">Category</div>
              <select
                value={filterCategory}
                onChange={(event) => setFilterCategory(event.target.value)}
                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
              >
                <option value="">All categories</option>
                {(categoriesQuery.data ?? []).map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>

              <label className="mt-3 flex items-center gap-2 text-sm text-gray-300">
                <input
                  type="checkbox"
                  checked={filterInStoreOnly}
                  onChange={(event) => setFilterInStoreOnly(event.target.checked)}
                  className="h-4 w-4 accent-orange-500"
                />
                In-store products only
              </label>
            </div>

            <div className="flex flex-col justify-between gap-3">
              <button
                onClick={() => loopFilterMutation.mutate()}
                disabled={loopFilterMutation.isPending}
                className="inline-flex items-center justify-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-gray-950 transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loopFilterMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Repeat className="h-4 w-4" />}
                Start Loop
              </button>
              {loopInfo && (
                <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-400">
                  Now looping <span className="text-gray-200 font-semibold">{loopInfo.video_count ?? 0}</span> video
                  {loopInfo.video_count === 1 ? "" : "s"} across {loopInfo.matched_products ?? 0} matching product
                  {loopInfo.matched_products === 1 ? "" : "s"}.
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      <section className="rounded-3xl border border-gray-800 bg-gray-900 p-4 shadow-2xl shadow-black/20">
        <label className="flex items-center gap-3 rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3">
          <Search className="h-4 w-4 text-gray-500" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search products by name or item number..."
            className="w-full bg-transparent text-sm text-gray-100 placeholder:text-gray-600 focus:outline-none"
          />
          {searching && <Loader2 className="h-4 w-4 animate-spin text-gray-500" />}
        </label>
        {!showResults && (
          <div className="mt-3 text-xs uppercase tracking-[0.22em] text-gray-500">Showing recently in-store products — search to find anything else</div>
        )}
        {playError && (
          <div className="mt-3 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-200">{playError}</div>
        )}
      </section>

      <section>
        {showResults && results.length === 0 && !searching ? (
          <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 px-6 py-16 text-center text-sm text-gray-500">
            No products match the current search.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {listToShow.map((product) => {
              const active = lastPlayed?.id === product.id && playing;
              return (
                <button
                  key={product.id}
                  onClick={() => playMutation.mutate(product)}
                  disabled={playMutation.isPending}
                  className={`group rounded-3xl border p-4 text-left transition ${
                    active ? "border-orange-500 bg-orange-500/10 shadow-lg shadow-orange-500/10" : "border-gray-800 bg-gray-900 hover:border-gray-700 hover:bg-gray-800"
                  } disabled:cursor-not-allowed disabled:opacity-80`}
                >
                  <div className="flex items-start gap-3">
                    <ProductImage imageUrl={product.image_url} name={product.name} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-base font-semibold text-gray-50 transition group-hover:text-orange-100">{product.name}</div>
                      <div className="mt-1 text-xs text-gray-500">{product.item_number || "No item number"} {product.brand_name ? `· ${product.brand_name}` : ""}</div>
                    </div>
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] uppercase tracking-[0.22em] ${
                        active ? "border-orange-500/50 bg-orange-500/15 text-orange-200" : "border-gray-700 bg-gray-950 text-gray-400"
                      }`}
                    >
                      <PlayCircle className="h-3 w-3" />
                      {active ? "Playing" : "Play"}
                    </span>
                    {playMutation.isPending && playMutation.variables?.id === product.id ? (
                      <Loader2 className="h-4 w-4 animate-spin text-orange-400" />
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
