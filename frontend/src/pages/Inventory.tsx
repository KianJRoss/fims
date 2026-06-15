import { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Barcode, Loader2, Search, Link } from "lucide-react";

import { api } from "../api/client";
import { useScannerStream } from "../hooks/useScannerStream";

type InventorySummary = {
  total_products: number;
  in_store_count: number;
  in_store_with_video: number;
  in_store_without_video: number;
};

type InventoryScanResponse =
  | { found: false; barcode: string }
  | {
      found: true;
      product: {
        id: string;
        name: string;
        item_number: string | null;
        brand: string | null;
        supplier: string | null;
        category: string | null;
        in_store: boolean;
      };
      video_match: { filename: string } | null;
      newly_marked: boolean;
    };

type ProductSearchResult = {
  id: string;
  name: string;
  item_number: string | null;
  brand: string | null;
};

type SessionScan = Extract<InventoryScanResponse, { found: true }> & {
  scanned_at: number;
};

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return target.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
}

function formatScanNumber(value: string | null | undefined) {
  return value && value.trim() ? value : "No item number";
}

export default function Inventory() {
  const [currentScan, setCurrentScan] = useState<InventoryScanResponse | null>(null);
  const [sessionScans, setSessionScans] = useState<SessionScan[]>([]);
  const [linkSearch, setLinkSearch] = useState("");
  const [linkResults, setLinkResults] = useState<ProductSearchResult[]>([]);
  const [linkSearching, setLinkSearching] = useState(false);
  const bufferRef = useRef("");
  const timerRef = useRef<number | null>(null);
  const searchTimerRef = useRef<number | null>(null);

  const summaryQuery = useQuery({
    queryKey: ["inventory-summary"],
    queryFn: async (): Promise<InventorySummary> => (await api.get("/v1/inventory/summary")).data,
    refetchOnWindowFocus: false,
  });

  const scanMutation = useMutation({
    mutationFn: async (barcode: string) => {
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan", { barcode });
      return data;
    },
    onSuccess: async (data) => {
      setCurrentScan(data);
      if (data.found) {
        setSessionScans((cur) => [{ ...data, scanned_at: Date.now() }, ...cur]);
        setLinkSearch("");
        setLinkResults([]);
      }
      await summaryQuery.refetch();
    },
  });

  const scanBarcode = useCallback((barcode: string) => {
    scanMutation.mutate(barcode);
  }, [scanMutation.mutate]);

  const linkMutation = useMutation({
    mutationFn: async ({ productId, barcode }: { productId: string; barcode: string }) => {
      // Add the barcode to this product, then re-scan so it marks in_store + pairs video
      await api.post(`/v1/products/${productId}/barcodes`, { barcode, is_primary: true });
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan", { barcode });
      return data;
    },
    onSuccess: async (data) => {
      setCurrentScan(data);
      if (data.found) {
        setSessionScans((cur) => [{ ...data, scanned_at: Date.now() }, ...cur]);
      }
      setLinkSearch("");
      setLinkResults([]);
      await summaryQuery.refetch();
    },
  });

  const pairVideosMutation = useMutation({
    mutationFn: async () => (await api.post("/v1/inventory/pair-videos")).data,
    onSuccess: () => summaryQuery.refetch(),
  });

  useScannerStream(scanBarcode);

  // Keyboard barcode listener
  useEffect(() => {
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
  }, [scanMutation.isPending, scanBarcode]);

  // Product search for link workflow
  useEffect(() => {
    if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    if (linkSearch.trim().length < 2) { setLinkResults([]); return; }

    searchTimerRef.current = window.setTimeout(async () => {
      setLinkSearching(true);
      try {
        const { data } = await api.get("/v1/products", { params: { search: linkSearch.trim(), size: 8 } });
        setLinkResults(Array.isArray(data) ? data : (data.items ?? []));
      } catch {
        setLinkResults([]);
      } finally {
        setLinkSearching(false);
      }
    }, 300);

    return () => { if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current); };
  }, [linkSearch]);

  const unknownBarcode = currentScan && !currentScan.found ? currentScan.barcode : null;
  const inStoreCount = summaryQuery.data?.in_store_count ?? 0;
  const hasCurrentVideo = currentScan?.found ? Boolean(currentScan.video_match) : false;

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-5 backdrop-blur">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.35em] text-orange-300/80">
              <Barcode className="h-4 w-4" />
              Inventory Scanner
            </div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Barcode-driven in-store tracking</h1>
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
          </div>
        </div>
      </div>

      <div className="space-y-6 px-6 py-6">
        {/* Current scan result */}
        <section className="rounded-3xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-950 p-6 shadow-2xl shadow-black/20">
          <div className="flex min-h-[22rem] items-center justify-center">
            {!currentScan ? (
              <div className="text-center">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-gray-800 bg-gray-950 text-orange-300">
                  <Barcode className="h-7 w-7" />
                </div>
                <div className="mt-5 text-2xl font-semibold text-gray-50">Scan a barcode to begin</div>
                <div className="mt-2 text-sm text-gray-500">The most recent scan will appear here.</div>
              </div>
            ) : currentScan.found ? (
              <div className="w-full max-w-4xl rounded-[2rem] border border-gray-800 bg-gray-950/90 p-6">
                <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Latest Scan</div>
                    <h2 className="mt-2 text-4xl font-semibold tracking-tight text-gray-50">{currentScan.product.name}</h2>
                    <div className="mt-3 text-sm text-orange-200">{formatScanNumber(currentScan.product.item_number)}</div>
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
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3 lg:min-w-[28rem]">
                    <MetaCard label="Brand" value={currentScan.product.brand || "None"} />
                    <MetaCard label="Supplier" value={currentScan.product.supplier || "None"} />
                    <MetaCard label="Category" value={currentScan.product.category || "None"} />
                  </div>
                </div>
              </div>
            ) : (
              /* Unknown barcode — show link workflow */
              <div className="w-full max-w-2xl space-y-4">
                <div className="rounded-[2rem] border border-red-500/30 bg-red-500/10 p-6">
                  <div className="text-xs uppercase tracking-[0.25em] text-red-200/70">Unknown Barcode</div>
                  <div className="mt-2 text-2xl font-semibold text-red-100 font-mono">{currentScan.barcode}</div>
                  <div className="mt-1 text-sm text-red-200/80">Search below to link this barcode to the correct product.</div>
                </div>

                <div className="rounded-3xl border border-gray-800 bg-gray-900 p-5 space-y-3">
                  <div className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-gray-400">
                    <Link className="h-3.5 w-3.5" />
                    Link to product
                  </div>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                    <input
                      type="text"
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
                          <div className="font-medium text-gray-100">{p.name}</div>
                          <div className="mt-0.5 text-xs text-gray-500">{p.item_number} {p.brand ? `· ${p.brand}` : ""}</div>
                        </button>
                      ))}
                    </div>
                  )}

                  {linkMutation.isPending && (
                    <div className="flex items-center gap-2 text-sm text-gray-400">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Linking barcode and marking in store...
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Session list */}
        <section className="rounded-3xl border border-gray-800 bg-gray-900 p-4 shadow-2xl shadow-black/10">
          <div className="flex items-center justify-between gap-3 border-b border-gray-800 px-2 pb-3">
            <div>
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Session List</div>
              <div className="mt-1 text-sm text-gray-400">Most recent scan first</div>
            </div>
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">{sessionScans.length} scans</div>
          </div>
          <div className="mt-4 max-h-[28rem] space-y-3 overflow-auto pr-1">
            {sessionScans.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-4 py-8 text-center text-sm text-gray-500">
                Scanned products will appear here for this session.
              </div>
            ) : (
              sessionScans.map((scan) => (
                <div key={`${scan.product.id}-${scan.scanned_at}`} className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0">
                      <div className="truncate text-base font-semibold text-gray-50">{scan.product.name}</div>
                      <div className="mt-1 text-sm text-orange-200">{formatScanNumber(scan.product.item_number)}</div>
                      <div className="mt-2 flex flex-wrap gap-2 text-xs">
                        <span className="rounded-full border border-gray-700 bg-gray-900 px-2.5 py-1 text-gray-300">{scan.product.brand || "No brand"}</span>
                        <span className="rounded-full border border-gray-700 bg-gray-900 px-2.5 py-1 text-gray-300">{scan.product.category || "No category"}</span>
                        <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-200">In Store</span>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {scan.video_match ? (
                        <span className="rounded-full border border-orange-500/40 bg-orange-500/10 px-3 py-1.5 text-xs uppercase tracking-[0.2em] text-orange-200">Video</span>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function MetaCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.25em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-gray-100">{value}</div>
    </div>
  );
}
