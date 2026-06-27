import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeDollarSign,
  Barcode,
  ChevronRight,
  ClipboardList,
  Building2,
  FilterX,
  Link as LinkIcon,
  ListChecks,
  Loader2,
  PencilLine,
  PenSquare,
  Plus,
  Save,
  Search,
  X,
} from "lucide-react";

import { api } from "../api/client";
import BarcodePrint from "./BarcodePrint";
import Suppliers from "./Suppliers";
import Deals from "./Deals";
import { useScannerStream } from "../hooks/useScannerStream";
import { useScannerClaim } from "../hooks/useScannerClaim";
import ProductImage from "../components/ProductImage";
import ManualProductEntry from "../components/ManualProductEntry";

// ─────────────────────────────────────────────────────────────────────────
// Shared types
// ─────────────────────────────────────────────────────────────────────────

type View = "catalog" | "initialize" | "data-entry" | "pricing" | "barcodes" | "suppliers" | "deals";

type Brand = { id: number; name: string };

type ProductSummary = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  category_name: string | null;
  brand_name: string | null;
  barcode_count: number;
  video_count: number;
  in_store: boolean;
  shot_count: number | null;
  catalog_page: number | null;
  created_at: string;
};

type ProductBarcode = {
  id: number;
  barcode: string;
  barcode_type: string;
  is_primary: boolean;
  notes: string | null;
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

type ProductAlias = {
  id: number;
  product_id: string;
  alias_name: string;
  source: string | null;
  created_at: string;
};

type ProductDetail = ProductSummary & {
  description: string | null;
  notes: string | null;
  category_id: number | null;
  brand_id: number | null;
  duration_seconds: number | null;
  effects: string | null;
  is_active: boolean;
  no_video_confirmed: boolean;
  catalog_page: number | null;
  updated_at: string;
  barcodes: ProductBarcode[];
  videos: ProductVideo[];
};

type ProductPage = ProductSummary[];

type ProductMode = "all" | "in_store" | "catalog";
type ProductSort = "name" | "brand" | "recent" | "catalog";

function formatDate(value: string | null | undefined) {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString();
}

function formatDuration(totalSeconds: number | null) {
  if (totalSeconds === null || Number.isNaN(totalSeconds)) return "Unknown";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function badgeTone(value: boolean) {
  return value
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
    : "border-slate-700 bg-slate-900 text-slate-300";
}

const VIEW_TABS: { id: View; label: string; icon: typeof ListChecks }[] = [
  { id: "catalog", label: "Catalog", icon: Search },
  { id: "initialize", label: "Initialization", icon: ListChecks },
  { id: "data-entry", label: "Data Entry", icon: PenSquare },
  { id: "pricing", label: "Pricing", icon: BadgeDollarSign },
  { id: "barcodes", label: "Barcodes", icon: Barcode },
  { id: "suppliers", label: "Suppliers", icon: Building2 },
  { id: "deals", label: "Deals", icon: ChevronRight },
];

export default function ProductCatalog() {
  const [view, setView] = useState<View>("catalog");

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Products</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {view === "catalog"
              ? "Catalog"
              : view === "initialize"
              ? "Product Initialization"
              : view === "data-entry"
              ? "Data Entry"
              : view === "pricing"
              ? "Pricing"
              : view === "barcodes"
              ? "Barcodes"
              : view === "suppliers"
              ? "Suppliers"
              : "Deals"}
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

      {view === "catalog" && <CatalogView />}
      {view === "initialize" && <InitializeView />}
      {view === "data-entry" && <DataEntryView />}
      {view === "pricing" && <PricingView />}
      {view === "barcodes" && <BarcodePrint />}
      {view === "suppliers" && <Suppliers />}
      {view === "deals" && <Deals />}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Catalog view (browse/search/edit-detail) — formerly the whole Products page
// ─────────────────────────────────────────────────────────────────────────

function CatalogView() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [mode, setMode] = useState<ProductMode>("all");
  const [brandIds, setBrandIds] = useState<number[]>([]);
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<ProductSort>("name");
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);
  const [newAliasName, setNewAliasName] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const brandsQuery = useQuery({
    queryKey: ["brands", "catalog"],
    queryFn: async (): Promise<Brand[]> => (await api.get("/v1/brands/")).data,
  });

  const categoriesQuery = useQuery({
    queryKey: ["product-categories"],
    queryFn: async (): Promise<string[]> => (await api.get("/v1/products/categories")).data,
  });

  useEffect(() => {
    if (mode === "catalog") setSort("catalog");
    else if (sort === "catalog") setSort("name");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const productsQuery = useInfiniteQuery({
    queryKey: ["product-catalog", debouncedSearch, mode, brandIds, category, sort],
    queryFn: async ({ pageParam = 0 }): Promise<ProductPage> => {
      const params = new URLSearchParams();
      params.set("skip", String(pageParam));
      params.set("limit", "50");
      params.set("sort", sort);
      if (debouncedSearch) params.set("q", debouncedSearch);
      if (category) params.set("category", category);
      if (mode === "in_store") params.set("in_store", "true");
      if (mode === "catalog") params.set("in_store", "false");
      for (const id of brandIds) params.append("brand_id", String(id));
      const { data } = await api.get(`/v1/products/?${params.toString()}`);
      return data;
    },
    getNextPageParam: (lastPage, allPages) => (lastPage.length === 50 ? allPages.length * 50 : undefined),
    initialPageParam: 0,
  });

  const products = useMemo(
    () => productsQuery.data?.pages.flatMap((page) => page) ?? [],
    [productsQuery.data]
  );

  useEffect(() => {
    if (selectedProductId && products.length > 0 && !products.some((item) => item.id === selectedProductId)) {
      setSelectedProductId(null);
    }
  }, [products, selectedProductId]);

  const selectedProductQuery = useQuery({
    queryKey: ["product-detail", selectedProductId],
    queryFn: async (): Promise<ProductDetail> => (await api.get(`/v1/products/${selectedProductId}`)).data,
    enabled: Boolean(selectedProductId),
    refetchOnWindowFocus: false,
  });

  const inStoreMutation = useMutation({
    mutationFn: async (payload: { productId: string; inStore: boolean }) => {
      const { data } = await api.patch(`/v1/products/${payload.productId}/in-store`, { in_store: payload.inStore });
      return data as ProductDetail;
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
      await queryClient.invalidateQueries({ queryKey: ["product-detail", variables.productId] });
    },
  });

  const aliasesQuery = useQuery({
    queryKey: ["product-aliases", selectedProductId],
    queryFn: async (): Promise<ProductAlias[]> => (await api.get(`/v1/products/${selectedProductId}/aliases`)).data,
    enabled: Boolean(selectedProductId),
    refetchOnWindowFocus: false,
  });

  const addAliasMutation = useMutation({
    mutationFn: async (payload: { productId: string; aliasName: string }) => {
      const { data } = await api.post(`/v1/products/${payload.productId}/aliases`, {
        alias_name: payload.aliasName,
        source: "manual",
      });
      return data as ProductAlias;
    },
    onSuccess: async (_, variables) => {
      setNewAliasName("");
      await queryClient.invalidateQueries({ queryKey: ["product-aliases", variables.productId] });
    },
  });

  const removeAliasMutation = useMutation({
    mutationFn: async (payload: { productId: string; aliasId: number }) => {
      await api.delete(`/v1/products/${payload.productId}/aliases/${payload.aliasId}`);
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["product-aliases", variables.productId] });
    },
  });

  const clearFilters = () => {
    setSearch("");
    setDebouncedSearch("");
    setMode("all");
    setBrandIds([]);
    setCategory("");
    setSort("name");
  };

  const activeProduct = selectedProductQuery.data;
  const activeSummary = products.find((item) => item.id === selectedProductId) ?? null;
  const totalCount = products.length;

  return (
    <div className="flex min-h-[calc(100vh-81px)] flex-col lg:flex-row">
      <aside className="w-full shrink-0 border-b border-gray-800 bg-gray-900/90 px-4 py-5 lg:w-56 lg:border-b-0 lg:border-r">
        <div className="space-y-5">
          <div>
            <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Search</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search products"
                className="w-full rounded-2xl border border-gray-800 bg-gray-950 py-2.5 pl-9 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-orange-500"
              />
            </div>
            <div className="mt-2 text-[11px] uppercase tracking-[0.2em] text-gray-500">
              {productsQuery.isFetching ? "Refreshing" : "300ms debounce"}
            </div>
          </div>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">View</div>
            <div className="space-y-2">
              {[
                { value: "all", label: "Show All" },
                { value: "in_store", label: "In Store" },
                { value: "catalog", label: "Catalog" },
              ].map((option) => (
                <label
                  key={option.value}
                  className={`flex cursor-pointer items-center justify-between rounded-2xl border px-3 py-2 text-sm transition ${
                    mode === option.value
                      ? "border-orange-500 bg-orange-500/10 text-orange-100"
                      : "border-gray-800 bg-gray-950 text-gray-300 hover:border-gray-700"
                  }`}
                >
                  <span>{option.label}</span>
                  <input
                    type="radio"
                    checked={mode === option.value}
                    onChange={() => setMode(option.value as ProductMode)}
                    className="accent-orange-500"
                  />
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Brands</span>
              {brandIds.length > 0 && (
                <button onClick={() => setBrandIds([])} className="text-[11px] text-orange-400 hover:text-orange-300">
                  Clear
                </button>
              )}
            </div>
            <div className="max-h-40 overflow-y-auto space-y-1 pr-1">
              {(brandsQuery.data ?? []).map((brand) => {
                const checked = brandIds.includes(brand.id);
                return (
                  <label
                    key={brand.id}
                    className={`flex cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-1.5 text-xs transition ${
                      checked
                        ? "border-orange-500/60 bg-orange-500/10 text-orange-100"
                        : "border-gray-800 bg-gray-950 text-gray-400 hover:border-gray-700 hover:text-gray-200"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() =>
                        setBrandIds((prev) => (checked ? prev.filter((id) => id !== brand.id) : [...prev, brand.id]))
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
            <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Category</label>
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
            >
              <option value="">All categories</option>
              {(categoriesQuery.data ?? []).map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={clearFilters}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-300 transition hover:border-gray-700 hover:text-gray-100"
          >
            <FilterX className="h-4 w-4" />
            Clear filters
          </button>
        </div>
      </aside>

      <main className="relative flex-1 overflow-hidden">
        <div className="flex h-full flex-col">
          <div className="flex items-center justify-between gap-3 border-b border-gray-800 px-6 py-3">
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">{totalCount.toLocaleString()} products</div>
            <label className="rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2">
              <span className="sr-only">Sort products</span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as ProductSort)}
                className="bg-transparent text-sm text-gray-100 outline-none"
              >
                <option value="name">Name A-Z</option>
                <option value="brand">Brand</option>
                <option value="catalog">Catalog Page</option>
                <option value="recent">Recently Added</option>
              </select>
            </label>
          </div>
          <div className="flex-1 overflow-auto px-6 py-6">
            {productsQuery.isLoading ? (
              <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">Loading products...</div>
            ) : (
              <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                {products.map((product) => {
                  const isActive = product.id === selectedProductId;
                  return (
                    <button
                      key={product.id}
                      onClick={() => {
                        setSelectedProductId(product.id);
                        setNewAliasName("");
                      }}
                      className={`group rounded-3xl border p-4 text-left transition ${
                        isActive
                          ? "border-orange-500 bg-orange-500/10 shadow-lg shadow-orange-950/20"
                          : "border-gray-800 bg-gray-900 hover:border-gray-700 hover:bg-gray-900/95"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        {product.image_url && (
                          <div className="flex-shrink-0 h-16 w-16 rounded-xl bg-gray-800 overflow-hidden flex items-center justify-center">
                            <img
                              src={product.image_url}
                              alt={product.name}
                              className="h-full w-full object-contain p-1"
                              onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = "none"; }}
                            />
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-lg font-semibold text-gray-50">{product.name}</div>
                          <div className="mt-2 text-sm font-medium text-orange-300">{product.item_number || "No item number"}</div>
                        </div>
                        <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-gray-600 transition group-hover:text-gray-400" />
                      </div>

                      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
                        <span className={`rounded-full border px-2.5 py-1 ${badgeTone(product.in_store)}`}>
                          {product.in_store ? "In Store" : "Catalog"}
                        </span>
                        <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-gray-300">
                          {product.brand_name || "No brand"}
                        </span>
                        <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-gray-300">
                          {product.barcode_count} barcodes
                        </span>
                        <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-gray-300">
                          {product.video_count} videos
                        </span>
                      </div>

                      <div className="mt-4 flex items-center justify-between text-xs text-gray-500">
                        <span>
                          {product.category_name || "No category"}
                          {product.catalog_page ? ` · p.${product.catalog_page}` : ""}
                        </span>
                        <label className="flex items-center gap-2 text-emerald-300" onClick={(event) => event.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={product.in_store}
                            onChange={(event) => inStoreMutation.mutate({ productId: product.id, inStore: event.target.checked })}
                            className="h-4 w-4 accent-emerald-500"
                          />
                          In Store
                        </label>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {!productsQuery.isLoading && products.length === 0 && (
              <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-10 text-center text-sm text-gray-500">
                No products match the current filters.
              </div>
            )}

            <div className="mt-6 flex justify-center">
              <button
                onClick={() => productsQuery.fetchNextPage()}
                disabled={!productsQuery.hasNextPage || productsQuery.isFetchingNextPage}
                className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
              >
                {productsQuery.isFetchingNextPage ? "Loading..." : productsQuery.hasNextPage ? "Load More" : "No More Products"}
              </button>
            </div>
          </div>
        </div>

        {selectedProductId && (
          <div className="fixed inset-y-0 right-0 z-30 w-full border-l border-gray-800 bg-gray-900 shadow-2xl shadow-black/50 sm:w-96">
            <div className="flex h-full flex-col">
              <div className="flex items-start justify-between border-b border-gray-800 px-5 py-4">
                <div>
                  <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Product Detail</div>
                  <div className="mt-2 text-lg font-semibold text-gray-50">{activeProduct?.name || activeSummary?.name || "Loading..."}</div>
                </div>
                <button
                  onClick={() => setSelectedProductId(null)}
                  className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-400 transition hover:text-gray-100"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="flex-1 overflow-auto px-5 py-4">
                {selectedProductQuery.isLoading ? (
                  <div className="rounded-2xl border border-gray-800 bg-gray-950 p-4 text-sm text-gray-400">Loading product detail...</div>
                ) : activeProduct ? (
                  <div className="space-y-5">
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 p-4">
                      {activeProduct.image_url && (
                        <div className="mb-4 flex items-center justify-center rounded-xl bg-gray-900 overflow-hidden h-40">
                          <img
                            src={activeProduct.image_url}
                            alt={activeProduct.name}
                            className="h-full w-full object-contain p-2"
                            onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = "none"; }}
                          />
                        </div>
                      )}
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="text-2xl font-semibold text-gray-50">{activeProduct.name}</div>
                          <div className="mt-1 text-sm text-orange-300">{activeProduct.item_number || "No item number"}</div>
                        </div>
                        <label className="flex items-center gap-2 text-sm text-emerald-300">
                          <input
                            type="checkbox"
                            checked={activeProduct.in_store}
                            onChange={(event) => inStoreMutation.mutate({ productId: activeProduct.id, inStore: event.target.checked })}
                            className="h-4 w-4 accent-emerald-500"
                          />
                          In Store
                        </label>
                      </div>

                      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                        <Meta label="Brand" value={activeProduct.brand_name || "None"} />
                        <Meta label="Category" value={activeProduct.category_name || "None"} />
                        <Meta label="Shot Count" value={activeProduct.shot_count?.toString() || "None"} />
                        <Meta label="Catalog Page" value={activeProduct.catalog_page?.toString() || "—"} />
                        <Meta label="Duration" value={formatDuration(activeProduct.duration_seconds)} />
                      </div>

                      <div className="mt-4 rounded-xl border border-gray-800 bg-gray-900 p-3 text-xs text-gray-400">
                        <div className="flex items-center justify-between">
                          <span>Created</span>
                          <span>{formatDate(activeProduct.created_at)}</span>
                        </div>
                        <div className="mt-2 flex items-center justify-between">
                          <span>Updated</span>
                          <span>{formatDate(activeProduct.updated_at)}</span>
                        </div>
                        <div className="mt-2 flex items-center justify-between">
                          <span>Video Count</span>
                          <span>{activeProduct.video_count}</span>
                        </div>
                      </div>
                    </div>

                    <section className="space-y-3 rounded-2xl border border-gray-800 bg-gray-950 p-4">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">All Fields</h3>
                      <Field label="Description" value={activeProduct.description || "None"} />
                      <Field label="Notes" value={activeProduct.notes || "None"} />
                      <Field label="Effects" value={activeProduct.effects || "None"} />
                      <Field label="No Video Confirmed" value={activeProduct.no_video_confirmed ? "Yes" : "No"} />
                      <Field label="Category ID" value={activeProduct.category_id?.toString() || "None"} />
                      <Field label="Brand ID" value={activeProduct.brand_id?.toString() || "None"} />
                    </section>

                    <section className="space-y-3 rounded-2xl border border-gray-800 bg-gray-950 p-4">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Barcodes</h3>
                      {activeProduct.barcodes.length === 0 ? (
                        <EmptyNote text="No barcodes attached." />
                      ) : (
                        <div className="space-y-2">
                          {activeProduct.barcodes.map((barcode) => (
                            <div key={barcode.id} className="rounded-xl border border-gray-800 bg-gray-900 px-3 py-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="font-medium text-gray-100">{barcode.barcode}</div>
                                {barcode.is_primary && (
                                  <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-1 text-[11px] text-orange-200">
                                    Primary
                                  </span>
                                )}
                              </div>
                              <div className="mt-1 text-xs text-gray-500">
                                {barcode.barcode_type}
                                {barcode.notes ? ` - ${barcode.notes}` : ""}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </section>

                    <section className="space-y-3 rounded-2xl border border-gray-800 bg-gray-950 p-4">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Also Known As</h3>
                      {aliasesQuery.isLoading ? (
                        <div className="text-sm text-gray-400">Loading aliases...</div>
                      ) : (aliasesQuery.data ?? []).length === 0 ? (
                        <EmptyNote text="No alternate names recorded." />
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {(aliasesQuery.data ?? []).map((alias) => (
                            <span key={alias.id} className="inline-flex items-center gap-2 rounded-full border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs text-gray-200">
                              {alias.alias_name}
                              <button
                                onClick={() => removeAliasMutation.mutate({ productId: activeProduct.id, aliasId: alias.id })}
                                className="text-gray-500 transition hover:text-orange-400"
                                aria-label={`Remove alias ${alias.alias_name}`}
                              >
                                <X className="h-3 w-3" />
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      <form
                        onSubmit={(event) => {
                          event.preventDefault();
                          const trimmed = newAliasName.trim();
                          if (!trimmed) return;
                          addAliasMutation.mutate({ productId: activeProduct.id, aliasName: trimmed });
                        }}
                        className="flex items-center gap-2"
                      >
                        <input
                          value={newAliasName}
                          onChange={(event) => setNewAliasName(event.target.value)}
                          placeholder="Add alternate name"
                          className="flex-1 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-orange-500"
                        />
                        <button
                          type="submit"
                          disabled={addAliasMutation.isPending || !newAliasName.trim()}
                          className="rounded-xl bg-orange-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                        >
                          Add
                        </button>
                      </form>
                    </section>

                    <section className="space-y-3 rounded-2xl border border-gray-800 bg-gray-950 p-4">
                      <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Videos</h3>
                      {activeProduct.videos.length === 0 ? (
                        <EmptyNote text="No videos attached." />
                      ) : (
                        <div className="space-y-3">
                          {activeProduct.videos.map((video) => (
                            <div key={video.id} className="rounded-2xl border border-gray-800 bg-gray-900 p-3">
                              <div className="flex gap-3">
                                <div className="h-16 w-24 shrink-0 overflow-hidden rounded-xl bg-gray-800">
                                  {video.youtube_id ? (
                                    <img
                                      src={video.thumbnail_url || `https://img.youtube.com/vi/${video.youtube_id}/hqdefault.jpg`}
                                      alt={video.title || "Video thumbnail"}
                                      className="h-full w-full object-cover"
                                    />
                                  ) : (
                                    <div className="flex h-full items-center justify-center text-[11px] text-gray-500">No thumb</div>
                                  )}
                                </div>
                                <div className="min-w-0 flex-1">
                                  <div
                                    className="text-sm font-medium text-gray-100"
                                    style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}
                                  >
                                    {video.title || "Untitled video"}
                                  </div>
                                  <div className="mt-1 text-xs text-gray-500">{video.original_filename || "Unknown source"}</div>
                                  <div className="mt-2 flex items-center gap-2 text-[11px] text-gray-400">
                                    <span className="rounded-full border border-gray-700 px-2 py-1">{video.download_status}</span>
                                    <span>{formatDuration(video.duration_seconds)}</span>
                                  </div>
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </section>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-gray-800 bg-gray-950 p-4 text-sm text-gray-400">Select a product to open the detail drawer.</div>
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm text-gray-100">{value}</div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">{label}</div>
      <div className="mt-1 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-100">{value}</div>
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-gray-800 px-3 py-6 text-center text-sm text-gray-500">{text}</div>;
}

// ─────────────────────────────────────────────────────────────────────────
// Initialize view (scan-driven, formerly the Inventory page)
// ─────────────────────────────────────────────────────────────────────────

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

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return target.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
}

function formatScanNumber(value: string | null | undefined) {
  return value && value.trim() ? value : "No item number";
}

function InitializeView() {
  const [currentScan, setCurrentScan] = useState<InventoryScanResponse | null>(null);
  const [linkSearch, setLinkSearch] = useState("");
  const [linkResults, setLinkResults] = useState<ProductSearchResult[]>([]);
  const [linkSearching, setLinkSearching] = useState(false);
  const [rejectedConfirmBarcode, setRejectedConfirmBarcode] = useState<string | null>(null);
  const [creatingNew, setCreatingNew] = useState(false);
  const bufferRef = useRef("");
  const timerRef = useRef<number | null>(null);
  const searchTimerRef = useRef<number | null>(null);

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
    if (scanMutation.isPending) return;
    scanMutation.mutate(barcode);
  }, [scanMutation.isPending, scanMutation.mutate]);

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
      await api.post(`/v1/products/${productId}/barcodes`, { barcode, is_primary: true });
      const { data } = await api.post<InventoryScanResponse>("/v1/inventory/scan", { barcode });
      if (data.found && data.needs_confirmation) {
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

  // Claim the scanner for inventory while this page is open and visible; it
  // auto-releases to the Remote when backgrounded/slept/closed.
  useScannerClaim("inventory");

  useScannerStream((barcode, target) => {
    if (target !== "inventory") {
      return;
    }
    scanBarcode(barcode);
  });

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
  const searchPanelBarcode = currentScan ? currentScan.barcode : null;

  function closeModal() {
    setCurrentScan(null);
    setRejectedConfirmBarcode(null);
    setCreatingNew(false);
    setLinkSearch("");
    setLinkResults([]);
  }

  const inStoreCount = summaryQuery.data?.in_store_count ?? 0;
  const hasCurrentVideo = currentScan?.found ? Boolean(currentScan.video_match) : false;
  const modalOpen = currentScan !== null;

  return (
    <div className="space-y-6 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-sm font-medium ${
          summaryQuery.isFetching ? "border-gray-700 bg-gray-900 text-gray-300" : "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
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
          {pairVideosMutation.isSuccess ? `Paired ${(pairVideosMutation.data as { paired: number }).paired} videos` : "Pair All Videos"}
        </button>
      </div>

      <section className="rounded-3xl border border-gray-800 bg-gradient-to-br from-gray-900 to-gray-950 p-10 text-center shadow-2xl shadow-black/20">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-3xl border border-gray-800 bg-gray-950 text-orange-300">
          <Barcode className="h-7 w-7" />
        </div>
        <div className="mt-5 text-2xl font-semibold text-gray-50">Scan a barcode</div>
        <div className="mt-2 text-sm text-gray-500">Each scan pops up here for a quick yes/no — nothing else to manage on this screen.</div>
      </section>

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

      {modalOpen && currentScan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4" onClick={closeModal}>
          <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-[2rem] border border-gray-800 bg-gray-950 p-6 shadow-2xl shadow-black/40" onClick={(e) => e.stopPropagation()}>
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
                    {currentScan.product.brand && <div className="mt-1 text-xs text-gray-500">{currentScan.product.brand}</div>}
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
                    <LinkIcon className="h-3.5 w-3.5" />
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
              <div className="space-y-5">
                <div className="flex items-center gap-4">
                  <ProductImage imageUrl={currentScan.product.image_url} name={currentScan.product.name} size="md" />
                  <div className="min-w-0">
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">In Store</div>
                    <h2 className="mt-1 text-2xl font-semibold tracking-tight text-gray-50">{currentScan.product.name}</h2>
                    <div className="mt-1 text-sm text-orange-200">{formatScanNumber(currentScan.product.item_number)}</div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
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
                <ManualProductEntry
                  initialEditProductId={currentScan.product.id}
                  onClose={closeModal}
                  onSaved={async () => {
                    await refreshAfterChange();
                    closeModal();
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Data entry view (manual search/add/edit + priority queue)
// ─────────────────────────────────────────────────────────────────────────

function DataEntryView() {
  return (
    <div className="space-y-6 px-4 py-6 sm:px-6">
      <ManualProductEntry />
      <DataEntryQueue />
    </div>
  );
}

function DataEntryQueue() {
  const reviewQueueQuery = useQuery({
    queryKey: ["inventory-review-queue"],
    queryFn: async (): Promise<ReviewQueueItem[]> =>
      (await api.get("/v1/inventory/products", { params: { needs_data_review: true, size: 100 } })).data,
    refetchOnWindowFocus: false,
  });

  const markReviewedMutation = useMutation({
    mutationFn: async (productId: string) => api.patch(`/v1/products/${productId}`, { needs_data_review: false }),
    onSuccess: async () => {
      await reviewQueueQuery.refetch();
    },
  });

  return (
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
  );
}

// ─────────────────────────────────────────────────────────────────────────
// Pricing view (costing/retail price management, formerly the Pricing page)
// ─────────────────────────────────────────────────────────────────────────

type CostingRow = {
  product_id: string;
  item_number: string | null;
  image_url: string | null;
  name: string;
  packing: string | null;
  boxes_per_case: number | null;
  units_per_box: number | null;
  case_cost: number | null;
  markup_multiplier: number | null;
  retail_price: number | null;
  category_name: string | null;
};

type CostingFormState = {
  product_id: string;
  boxes_per_case: string;
  units_per_box: string;
  case_cost: string;
  markup_multiplier: string;
  packing: string | null;
  name: string;
};

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${value.toFixed(2)}`;
}

function formatPacking(packing: string | null, boxes?: number | null, units?: number | null) {
  if (boxes !== undefined && boxes !== null && units !== undefined && units !== null) {
    return `${boxes} / ${units}`;
  }
  if (!packing) return "—";
  return packing.replace("/", " / ");
}

function parsePacking(packing: string | null) {
  if (!packing) return { boxes: "", units: "" };
  const [boxes, units] = packing.split("/");
  return { boxes: boxes?.trim() ?? "", units: units?.trim() ?? "" };
}

function computeRetailPreview(caseCost: string, boxesPerCase: string, unitsPerBox: string, markupMultiplier: string) {
  const cost = Number(caseCost);
  const boxes = Number(boxesPerCase);
  const units = Number(unitsPerBox);
  const markup = Number(markupMultiplier);
  if (![cost, boxes, units, markup].every(Number.isFinite) || boxes <= 0 || units <= 0) return null;
  const unitCost = cost / (boxes * units);
  return Math.round(unitCost * markup) - 0.05;
}

function PricingView() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<CostingFormState | null>(null);

  const costingQuery = useQuery({
    queryKey: ["costing"],
    queryFn: async (): Promise<CostingRow[]> => (await api.get<CostingRow[]>("/v1/costing/")).data,
  });

  useEffect(() => {
    if (!editing) return;
    const stillVisible = costingQuery.data?.some((row) => row.product_id === editing.product_id);
    if (!stillVisible) setEditing(null);
  }, [costingQuery.data, editing]);

  const previewRetail = useMemo(() => {
    if (!editing) return null;
    return computeRetailPreview(editing.case_cost, editing.boxes_per_case, editing.units_per_box, editing.markup_multiplier);
  }, [editing]);

  const upsertMutation = useMutation({
    mutationFn: async (payload: { product_id: string; boxes_per_case: number; units_per_box: number; case_cost: number; markup_multiplier: number }) => {
      const { data } = await api.post<CostingRow>("/v1/costing/", payload);
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["costing"] });
      setEditing(null);
    },
  });

  function beginEdit(row: CostingRow) {
    const packing = parsePacking(row.packing);
    setEditing({
      product_id: row.product_id,
      boxes_per_case: row.boxes_per_case?.toString() ?? packing.boxes,
      units_per_box: row.units_per_box?.toString() ?? packing.units,
      case_cost: row.case_cost?.toString() ?? "",
      markup_multiplier: row.markup_multiplier?.toString() ?? "",
      packing: row.packing,
      name: row.name,
    });
  }

  function updateField(field: keyof Omit<CostingFormState, "product_id" | "packing" | "name">, value: string) {
    setEditing((current) => (current ? { ...current, [field]: value } : current));
  }

  function saveEditing() {
    if (!editing) return;
    const boxes = Number(editing.boxes_per_case);
    const units = Number(editing.units_per_box);
    const caseCost = Number(editing.case_cost);
    const markup = Number(editing.markup_multiplier);
    if (![boxes, units, caseCost, markup].every(Number.isFinite) || boxes <= 0 || units <= 0) return;
    upsertMutation.mutate({ product_id: editing.product_id, boxes_per_case: boxes, units_per_box: units, case_cost: caseCost, markup_multiplier: markup });
  }

  return (
    <div className="px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <div className="rounded-3xl border border-gray-800 bg-gray-900 px-4 py-3 inline-block">
          <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Visible products</div>
          <div className="mt-1 text-2xl font-semibold text-gray-50">{costingQuery.data?.length?.toLocaleString() ?? "0"}</div>
        </div>

        <div className="space-y-4 lg:hidden">
          {costingQuery.isLoading ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">Loading pricing...</div>
          ) : costingQuery.isError ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-red-200">Unable to load pricing.</div>
          ) : (costingQuery.data ?? []).length === 0 ? (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-8 text-center text-sm text-gray-500">No in-store products found.</div>
          ) : (
            costingQuery.data?.map((row) => {
              const hasCosting = row.boxes_per_case !== null && row.units_per_box !== null && row.case_cost !== null;
              return (
                <div key={row.product_id} className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-start gap-3">
                    <ProductImage imageUrl={row.image_url} name={row.name} size="xs" />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-gray-50">{row.name}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {row.item_number || "No item number"}
                        {row.category_name ? ` · ${row.category_name}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => beginEdit(row)}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-medium text-gray-100 transition hover:border-orange-500 hover:text-orange-200"
                    >
                      {hasCosting ? <PencilLine className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                      {hasCosting ? "Edit" : "Add"}
                    </button>
                  </div>

                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Packing</div>
                      <div className="mt-1 text-gray-300">{formatPacking(row.packing, row.boxes_per_case, row.units_per_box)}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Retail</div>
                      <div className="mt-1 text-gray-300">{formatMoney(row.retail_price)}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Case cost</div>
                      <div className="mt-1 text-gray-300">{formatMoney(row.case_cost)}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Markup</div>
                      <div className="mt-1 text-gray-300">{row.markup_multiplier === null ? "—" : row.markup_multiplier.toFixed(4)}</div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="hidden overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 lg:block">
          <table className="min-w-full divide-y divide-gray-800">
            <thead className="bg-gray-950">
              <tr className="text-left text-xs uppercase tracking-[0.2em] text-gray-500">
                <th className="px-4 py-3">Product name</th>
                <th className="px-4 py-3">Packing</th>
                <th className="px-4 py-3 text-right">Case Cost</th>
                <th className="px-4 py-3 text-right">Markup</th>
                <th className="px-4 py-3 text-right">Retail Price</th>
                <th className="px-4 py-3 text-right">Edit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {costingQuery.isLoading ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-400">Loading pricing...</td></tr>
              ) : costingQuery.isError ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-red-200">Unable to load pricing.</td></tr>
              ) : (costingQuery.data ?? []).length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">No in-store products found.</td></tr>
              ) : (
                costingQuery.data?.map((row) => {
                  const hasCosting = row.boxes_per_case !== null && row.units_per_box !== null && row.case_cost !== null;
                  return (
                    <tr key={row.product_id} className="bg-transparent hover:bg-gray-800/40">
                      <td className="px-4 py-4 align-middle">
                        <div className="flex items-center gap-3">
                          <ProductImage imageUrl={row.image_url} name={row.name} size="xs" />
                          <div>
                            <div className="font-medium text-gray-50">{row.name}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {row.item_number || "No item number"}
                              {row.category_name ? ` · ${row.category_name}` : ""}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 align-middle text-sm text-gray-300">{formatPacking(row.packing, row.boxes_per_case, row.units_per_box)}</td>
                      <td className="px-4 py-4 align-middle text-right text-sm text-gray-200">{formatMoney(row.case_cost)}</td>
                      <td className="px-4 py-4 align-middle text-right text-sm text-gray-200">{row.markup_multiplier === null ? "—" : row.markup_multiplier.toFixed(4)}</td>
                      <td className="px-4 py-4 align-middle text-right">
                        {hasCosting ? (
                          <span className="inline-flex items-center gap-2 rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 text-sm font-semibold text-orange-200">
                            <BadgeDollarSign className="h-4 w-4" />
                            {formatMoney(row.retail_price)}
                          </span>
                        ) : (
                          <span className="inline-flex items-center rounded-full border border-gray-700 bg-gray-800 px-3 py-1 text-xs uppercase tracking-[0.2em] text-gray-400">No pricing</span>
                        )}
                      </td>
                      <td className="px-4 py-4 align-middle text-right">
                        <button
                          type="button"
                          onClick={() => beginEdit(row)}
                          className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-medium text-gray-100 transition hover:border-orange-500 hover:text-orange-200"
                        >
                          {hasCosting ? <PencilLine className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                          {hasCosting ? "Edit" : "Add"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4 sm:py-8">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl sm:max-h-[90vh] sm:max-w-[42rem]">
            <div className="flex items-start justify-between gap-4 border-b border-gray-800 px-4 py-5 sm:px-6">
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Edit pricing</div>
                <h2 className="mt-2 text-2xl font-semibold text-gray-50">{editing.name}</h2>
                <div className="mt-1 text-sm text-gray-400">{editing.packing || "No packing on file"}</div>
              </div>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="rounded-2xl border border-gray-800 bg-gray-950 p-2 text-gray-400 transition hover:border-gray-700 hover:text-gray-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(100vh-14rem)] overflow-auto px-4 py-6 sm:max-h-none sm:px-6 md:grid md:grid-cols-2 md:gap-4">
              <PricingField label="Boxes per case" value={editing.boxes_per_case} onChange={(value) => updateField("boxes_per_case", value)} type="number" min="1" />
              <PricingField label="Units per box" value={editing.units_per_box} onChange={(value) => updateField("units_per_box", value)} type="number" min="1" />
              <PricingField label="Case cost" value={editing.case_cost} onChange={(value) => updateField("case_cost", value)} type="number" min="0" step="0.01" />
              <PricingField label="Markup multiplier" value={editing.markup_multiplier} onChange={(value) => updateField("markup_multiplier", value)} type="number" min="0" step="0.0001" />
            </div>

            <div className="border-t border-gray-800 px-4 py-4 sm:px-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Retail preview</div>
                  <div className="mt-2 text-3xl font-semibold text-orange-200">{previewRetail === null ? "—" : formatMoney(previewRetail)}</div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setEditing(null)}
                    className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm font-medium text-gray-200 transition hover:border-gray-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveEditing}
                    disabled={upsertMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                  >
                    {upsertMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    Save pricing
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PricingField({
  label,
  value,
  onChange,
  type,
  min,
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type: "number" | "text";
  min?: string;
  step?: string;
}) {
  return (
    <label className="space-y-2 text-sm text-gray-300">
      <span className="text-xs uppercase tracking-[0.25em] text-gray-500">{label}</span>
      <input
        type={type}
        value={value}
        min={min}
        step={step}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-orange-500"
      />
    </label>
  );
}
