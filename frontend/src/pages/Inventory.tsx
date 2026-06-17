import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Barcode, Loader2, Search, Link, ClipboardList, X, ListChecks, PenSquare } from "lucide-react";

import { api } from "../api/client";
import { useScannerStream } from "../hooks/useScannerStream";
import ProductImage from "../components/ProductImage";
import ManualProductEntry from "../components/ManualProductEntry";

type InventorySummary = {
  total_products: number;
  in_store_count: number;
  in_store_with_video: number;
  in_store_without_video: number;
  needs_review_count: number;
};

type ScannedProduct = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand: string | null;
  supplier: string | null;
  category: string | null;
  in_store: boolean;
  needs_data_review: boolean;
};

type InventoryScanResponse =
  | { found: false; barcode: string }
  | {
      found: true;
      needs_confirmation: boolean;
      barcode: string;
      product: ScannedProduct;
      video_match: { filename: string } | null;
      newly_marked: boolean;
    };

type ProductSearchResult = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand: string | null;
};

type ReviewQueueItem = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand: string | null;
};

type RecentItem = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand: string | null;
  category: string | null;
  needs_data_review: boolean;
};

type Mode = "initialize" | "data-entry";

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return target.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
}

function formatScanNumber(value: string | null | undefined) {
  return value && value.trim() ? value : "No item number";
}

export default function Inventory() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("initialize");
  const [currentScan, setCurrentScan] = useState<InventoryScanResponse | null>(null);
  const [linkSearch, setLinkSearch] = useState("");
  const [linkResults, setLinkResults] = useState<ProductSearchResult[]>([]);
  const [linkSearching, setLinkSearching] = useState(false);
  const [rejectedConfirmBarcode, setRejectedConfirmBarcode] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);
  const bufferRef = useRef("");
  const timerRef = useRef<number | null>(null);
  const searchTimerRef = useRef<number | null>(null);
  const autoCloseTimerRef = useRef<number | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["inventory-summary"],
    queryFn: async (): Promise<InventorySummary> => (await api.get("/v1/inventory/summary")).data,
    refetchOnWindowFocus: false,
  });

  const recentQuery = useQuery({
    queryKey: ["inventory-recent"],
    queryFn: async (): Promise<RecentItem[]> =>
      (await api.get("/v1/inventory/products", { params: { in_store: true, sort: "recent", size: 20 } })).data,
    refetchOnWindowFocus: false,
  });

  const refreshAfterChange = useCallback(async () => {
    await Promise.all([summaryQuery.refetch(), recentQuery.refetch()]);
  }, [summaryQuery, recentQuery]);

  const scanMutation = useMutation({
    mutationFn: async (barcode: string) => {
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan", { barcode });
      return data;
    },
    onSuccess: async (data) => {
      setRejectedConfirmBarcode(null);
      setCreatingNew(false);
      setCurrentScan(data);
      setLinkSearch("");
      setLinkResults([]);
      await refreshAfterChange();
    },
  });

  const scanBarcode = useCallback((barcode: string) => {
    scanMutation.mutate(barcode);
  }, [scanMutation.mutate]);

  const confirmMutation = useMutation({
    mutationFn: async (productId: string) => {
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan/confirm", { product_id: productId });
      return data;
    },
    onSuccess: async (data) => {
      setCurrentScan(data);
      await refreshAfterChange();
    },
  });

  const linkMutation = useMutation({
    mutationFn: async ({ productId, barcode }: { productId: string; barcode: string }) => {
      // Add the barcode to this product, then re-scan so it marks in_store + pairs video
      await api.post(`/v1/products/${productId}/barcodes`, { barcode, is_primary: true });
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan", { barcode });
      if (data.found && data.needs_confirmation) {
        // We just attached the barcode ourselves, so the operator has already
        // confirmed this is the right product — skip the confirmation prompt.
        const confirmed = await api.post<InventoryScanResponse>("/v1/inventory/scan/confirm", { product_id: data.product.id });
        return confirmed.data;
      }
      return data;
    },
    onSuccess: async (data) => {
      setRejectedConfirmBarcode(null);
      setCurrentScan(data);
      setLinkSearch("");
      setLinkResults([]);
      await refreshAfterChange();
    },
  });

  const pairVideosMutation = useMutation({
    mutationFn: async () => (await api.post("/v1/inventory/pair-videos")).data,
    onSuccess: () => summaryQuery.refetch(),
  });

  const reviewQueueQuery = useQuery({
    queryKey: ["inventory-review-queue"],
    queryFn: async (): Promise<ReviewQueueItem[]> =>
      (await api.get("/v1/inventory/products", { params: { needs_data_review: true, size: 100 } })).data,
    enabled: mode === "data-entry",
    refetchOnWindowFocus: false,
  });

  const markReviewedMutation = useMutation({
    mutationFn: async (productId: string) => api.patch(`/v1/products/${productId}`, { needs_data_review: false }),
    onSuccess: async () => {
      await reviewQueueQuery.refetch();
      await summaryQuery.refetch();
    },
  });

  useScannerStream(mode === "initialize" ? scanBarcode : () => {});

  // Keyboard barcode listener (only while in Product Initialization mode)
  useEffect(() => {
    if (mode !== "initialize") return;

    const flushBuffer = () => {
      if (timerRef.current !== null) { window.clearTimeout(timerRef.current); timerRef.current = null; }
      const barcode = bufferRef.current.trim();
      bufferRef.current = "";
      if (barcode.length < 6 || scanMutation.isPending) return;
      scanBarcode(barcode);
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.key === "Enter") { event.preventDefault(); flushBuffer(); return; }
      if (event.key.length !== 1 || event.metaKey || event.ctrlKey || event.altKey) return;
      bufferRef.current += event.key;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(flushBuffer, 100);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [mode, scanMutation.isPending, scanBarcode]);

  // Product search for the "No, that's wrong" / unknown-barcode link workflow
  useEffect(() => {
    if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    if (linkSearch.trim().length < 2) { setLinkResults([]); return; }

    searchTimerRef.current = window.setTimeout(async () => {
      setLinkSearching(true);
      try {
        const { data } = await api.get("/v1/products/", { params: { q: linkSearch.trim(), limit: 8 } });
        setLinkResults(Array.isArray(data) ? data : (data.items ?? []));
      } catch {
        setLinkResults([]);
      } finally {
        setLinkSearching(false);
      }
    }, 300);

    return () => { if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current); };
  }, [linkSearch]);

  const needsConfirmation = Boolean(currentScan?.found && currentScan.needs_confirmation && !rejectedConfirmBarcode);
  const showSearchPanel =
    currentScan !== null &&
    !creatingNew &&
    (!currentScan.found || (currentScan.needs_confirmation && rejectedConfirmBarcode === currentScan.barcode));
  const isFinalSuccess = currentScan !== null && currentScan.found && !needsConfirmation && !showSearchPanel;
  const searchPanelBarcode = currentScan ? currentScan.barcode : null;

  // Auto-dismiss the modal a moment after we land on a final "all good" state,
  // so a fast scan-scan-scan workflow doesn't require clicking anything away.
  useEffect(() => {
    if (autoCloseTimerRef.current !== null) { window.clearTimeout(autoCloseTimerRef.current); autoCloseTimerRef.current = null; }
    if (isFinalSuccess) {
      autoCloseTimerRef.current = window.setTimeout(() => {
        setCurrentScan(null);
      }, 1400);
    }
    return () => {
      if (autoCloseTimerRef.current !== null) window.clearTimeout(autoCloseTimerRef.current);
    };
  }, [isFinalSuccess, currentScan]);

  function closeModal() {
    setCurrentScan(null);
    setRejectedConfirmBarcode(null);
    setCreatingNew(false);
    setLinkSearch("");
    setLinkResults([]);
  }

  const inStoreCount = summaryQuery.data?.in_store_count ?? 0;
  const needsReviewCount = summaryQuery.data?.needs_review_count ?? 0;
  const hasCurrentVideo = currentScan?.found ? Boolean(currentScan.video_match) : false;
  const modalOpen = currentScan !== null;

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-5 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.35em] text-orange-300/80">
              <Barcode className="h-4 w-4" />
              Inventory
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {mode === "initialize" ? "Product Initialization" : "Data Entry"}
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium ${
              summaryQuery.isFetching
                ? "border-gray-700 bg-gray-900 text-gray-300"
                : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
            }`}>
              {summaryQuery.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />}
              <span className="uppercase tracking-[0.25em]">{inStoreCount} in store</span>
            </div>

            {/* Mode toggle switch */}
            <div className="inline-flex items-center rounded-2xl border border-gray-800 bg-gray-900 p-1">
              <button
                onClick={() => setMode("initialize")}
                className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-semibold transition ${
                  mode === "initialize" ? "bg-orange-500 text-gray-950" : "text-gray-400 hover:text-gray-100"
                }`}
              >
                <ListChecks className="h-4 w-4" />
                Initialization
              </button>
              <button
                onClick={() => setMode("data-entry")}
                className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-semibold transition ${
                  mode === "data-entry" ? "bg-orange-500 text-gray-950" : "text-gray-400 hover:text-gray-100"
                }`}
              >
                <PenSquare className="h-4 w-4" />
                Data Entry
                {needsReviewCount > 0 && (
                  <span className="rounded-full bg-amber-500/30 px-2 py-0.5 text-xs text-amber-100">{needsReviewCount}</span>
                )}
              </button>
            </div>

            {mode === "initialize" && (
              <button
                onClick={() => pairVideosMutation.mutate()}
                disabled={pairVideosMutation.isPending}
                className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-100 transition hover:border-orange-500/50 hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pairVideosMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {pairVideosMutation.isSuccess
                  ? `Paired ${(pairVideosMutation.data as { paired: number }).paired} videos`
                  : "Pair All Videos"}
              </button>
            )}
          </div>
        </div>
      </div>

      {mode === "initialize" ? (
        <div className="space-y-6 px-4 py-6 sm:px-6">
          <section className="rounded-3xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-950 p-10 text-center shadow-2xl shadow-black/20">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-gray-800 bg-gray-950 text-orange-300">
              <Barcode className="h-7 w-7" />
            </div>
            <div className="mt-5 text-2xl font-semibold text-gray-50">Scan a barcode</div>
            <div className="mt-2 text-sm text-gray-500">Each scan pops up here for a quick yes/no — nothing else to manage on this screen.</div>
          </section>

          {/* Recently initialized — persists across navigation (backed by real in_store state, not page-local state) */}
          <section className="rounded-3xl border border-gray-800 bg-gray-900 p-4 shadow-2xl shadow-black/10">
            <div className="flex items-center justify-between gap-3 border-b border-gray-800 px-2 pb-3">
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Recently Initialized</div>
                <div className="mt-1 text-sm text-gray-400">Most recently marked in-store first</div>
              </div>
              {recentQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin text-gray-500" />}
            </div>
            <div className="mt-4 max-h-[28rem] space-y-3 overflow-auto pr-1">
              {(recentQuery.data?.length ?? 0) === 0 ? (
                <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-4 py-8 text-center text-sm text-gray-500">
                  Scanned products will show up here.
                </div>
              ) : (
                recentQuery.data!.map((item) => (
                  <div key={item.id} className="flex items-center gap-3 rounded-2xl border border-gray-800 bg-gray-950 px-4 py-4">
                    <ProductImage imageUrl={item.image_url} name={item.name} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-base font-semibold text-gray-50">{item.name}</div>
                      <div className="mt-1 text-sm text-orange-200">{formatScanNumber(item.item_number)}</div>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full border border-gray-700 bg-gray-900 px-2.5 py-1 text-gray-300">{item.brand || "No brand"}</span>
                        <span className="rounded-full border border-gray-700 bg-gray-900 px-2.5 py-1 text-gray-300">{item.category || "No category"}</span>
                        {item.needs_data_review && (
                          <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-amber-200">Needs More Data</span>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      ) : (
        <div className="space-y-6 px-4 py-6 sm:px-6">
          <ManualProductEntry />

          <section className="rounded-3xl border border-amber-500/30 bg-amber-500/5 p-5 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-amber-200/80">
                <ClipboardList className="h-3.5 w-3.5" />
                Needs More Data ({reviewQueueQuery.data?.length ?? 0})
              </div>
              {reviewQueueQuery.isFetching && <Loader2 className="h-4 w-4 animate-spin text-amber-200/60" />}
            </div>
            {(reviewQueueQuery.data?.length ?? 0) === 0 ? (
              <div className="rounded-2xl border border-dashed border-amber-500/20 bg-gray-950 px-4 py-6 text-center text-sm text-gray-500">
                Nothing in the priority queue right now.
              </div>
            ) : (
              <div className="space-y-2">
                {reviewQueueQuery.data!.map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-3 rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <ProductImage imageUrl={item.image_url} name={item.name} size="xs" />
                      <div className="min-w-0">
                        <div className="font-medium text-gray-100 truncate">{item.name}</div>
                        <div className="mt-0.5 text-xs text-gray-500">{formatScanNumber(item.item_number)} {item.brand ? `· ${item.brand}` : ""}</div>
                      </div>
                    </div>
                    <button
                      onClick={() => markReviewedMutation.mutate(item.id)}
                      disabled={markReviewedMutation.isPending}
                      className="shrink-0 rounded-xl border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs font-semibold text-gray-300 transition hover:border-emerald-500/40 hover:text-emerald-200 disabled:opacity-50"
                    >
                      Mark Reviewed
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {/* Scan popup modal — the only way to reach search/create from Product Initialization mode */}
      {modalOpen && currentScan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4" onClick={closeModal}>
          <div
            className="w-full max-w-xl rounded-[2rem] border border-gray-800 bg-gray-950 p-6 shadow-2xl shadow-black/40"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-end">
              <button onClick={closeModal} className="rounded-xl border border-gray-800 bg-gray-900 p-1.5 text-gray-400 hover:text-gray-200">
                <X className="h-4 w-4" />
              </button>
            </div>

            {needsConfirmation && currentScan.found ? (
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-amber-200/70">Is this the correct product?</div>
                <div className="mt-4 flex items-center gap-4">
                  <ProductImage imageUrl={currentScan.product.image_url} name={currentScan.product.name} size="md" />
                  <div className="min-w-0">
                    <h2 className="text-2xl font-semibold tracking-tight text-gray-50">{currentScan.product.name}</h2>
                    <div className="mt-1 text-sm text-orange-200">{formatScanNumber(currentScan.product.item_number)}</div>
                    <div className="mt-1 text-xs text-gray-500 font-mono">{currentScan.barcode}</div>
                    {currentScan.product.brand && (
                      <div className="mt-1 text-xs text-gray-500">{currentScan.product.brand}</div>
                    )}
                  </div>
                </div>
                <div className="mt-6 flex items-center gap-3">
                  <button
                    onClick={() => confirmMutation.mutate(currentScan.product.id)}
                    disabled={confirmMutation.isPending}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-2xl bg-emerald-500 px-5 py-3 text-sm font-semibold text-gray-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {confirmMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    Yes, add to In Store
                  </button>
                  <button
                    onClick={() => setRejectedConfirmBarcode(currentScan.barcode)}
                    disabled={confirmMutation.isPending}
                    className="inline-flex flex-1 items-center justify-center gap-2 rounded-2xl border border-gray-700 bg-gray-950 px-5 py-3 text-sm font-semibold text-gray-200 transition hover:border-red-500/40 hover:text-red-200 disabled:opacity-60"
                  >
                    No, that's wrong
                  </button>
                </div>
              </div>
            ) : showSearchPanel ? (
              <div className="space-y-4">
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-5">
                  <div className="text-xs uppercase tracking-[0.25em] text-red-200/70">
                    {currentScan.found ? "Barcode Confirmed Incorrect" : "Unknown Barcode"}
                  </div>
                  <div className="mt-2 text-xl font-semibold text-red-100 font-mono">{currentScan.barcode}</div>
                  <div className="mt-1 text-sm text-red-200/80">
                    {currentScan.found
                      ? "Search for the correct product — this barcode will be moved to whichever one you pick."
                      : "Search for the product, or create a new entry with this barcode."}
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-gray-400">
                    <Link className="h-3.5 w-3.5" />
                    Search the catalog
                  </div>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                    <input
                      type="text"
                      autoFocus
                      placeholder="Type product name or item number..."
                      value={linkSearch}
                      onChange={(e) => setLinkSearch(e.target.value)}
                      className="w-full rounded-2xl border border-gray-700 bg-gray-950 py-3 pl-10 pr-4 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60 focus:ring-1 focus:ring-orange-500/20"
                    />
                    {linkSearching && <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-gray-500" />}
                  </div>

                  {linkResults.length > 0 && (
                    <div className="space-y-1">
                      {linkResults.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => linkMutation.mutate({ productId: p.id, barcode: currentScan.barcode })}
                          disabled={linkMutation.isPending}
                          className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-4 py-3 text-left transition hover:border-orange-500/40 hover:bg-gray-800 disabled:opacity-50"
                        >
                          <div className="flex items-center gap-3">
                            <ProductImage imageUrl={p.image_url} name={p.name} size="xs" />
                            <div className="min-w-0">
                              <div className="font-medium text-gray-100">{p.name}</div>
                              <div className="mt-0.5 text-xs text-gray-500">{p.item_number} {p.brand ? `· ${p.brand}` : ""}</div>
                            </div>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}

                  {linkSearch.trim().length >= 2 && !linkSearching && linkResults.length === 0 && (
                    <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-4 py-4 text-center text-sm text-gray-500">
                      No matching products found.
                    </div>
                  )}

                  {linkMutation.isPending && (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Linking barcode and marking in store...
                    </div>
                  )}

                  <button
                    onClick={() => setCreatingNew(true)}
                    className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm font-semibold text-gray-200 transition hover:border-orange-500/50 hover:bg-gray-800"
                  >
                    + Not in the system — create a new product
                  </button>
                </div>
              </div>
            ) : creatingNew ? (
              <ManualProductEntry
                prefillBarcode={searchPanelBarcode}
                flagAsNewInStoreItem
                onClose={closeModal}
                onSaved={async () => {
                  await refreshAfterChange();
                  closeModal();
                }}
              />
            ) : currentScan.found ? (
              <div>
                <div className="flex items-center gap-4">
                  <ProductImage imageUrl={currentScan.product.image_url} name={currentScan.product.name} size="md" />
                  <div className="min-w-0">
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">In Store</div>
                    <h2 className="mt-1 text-2xl font-semibold tracking-tight text-gray-50">{currentScan.product.name}</h2>
                    <div className="mt-1 text-sm text-orange-200">{formatScanNumber(currentScan.product.item_number)}</div>
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs uppercase tracking-[0.22em] text-emerald-200">In Store</span>
                  <span className={`rounded-full border px-3 py-1.5 text-xs uppercase tracking-[0.22em] ${
                    hasCurrentVideo ? "border-orange-500/40 bg-orange-500/10 text-orange-200" : "border-gray-700 bg-gray-900 text-gray-300"
                  }`}>
                    {hasCurrentVideo ? "Video Paired" : "No Video"}
                  </span>
                  {currentScan.newly_marked ? (
                    <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs uppercase tracking-[0.22em] text-cyan-200">Newly Marked</span>
                  ) : null}
                  {currentScan.product.needs_data_review ? (
                    <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs uppercase tracking-[0.22em] text-amber-200">Needs More Data</span>
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
