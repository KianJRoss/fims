import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FilterX, Search, X } from "lucide-react";

type Brand = {
  id: number;
  name: string;
};

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

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });

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

export default function ProductCatalog() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [mode, setMode] = useState<ProductMode>("all");
  const [brandIds, setBrandIds] = useState<number[]>([]);
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState<ProductSort>("name");
  const [selectedProductId, setSelectedProductId] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const brandsQuery = useQuery({
    queryKey: ["brands", "catalog"],
    queryFn: async (): Promise<Brand[]> => {
      const { data } = await api.get("/v1/brands/");
      return data;
    },
  });

  const categoriesQuery = useQuery({
    queryKey: ["product-categories"],
    queryFn: async (): Promise<string[]> => {
      const { data } = await api.get("/v1/products/categories");
      return data;
    },
  });

  // Auto-switch to catalog sort when Catalog mode is selected
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

  // If the selected product scrolled off (filter change), clear the panel rather than re-opening it
  useEffect(() => {
    if (selectedProductId && products.length > 0 && !products.some((item) => item.id === selectedProductId)) {
      setSelectedProductId(null);
    }
  }, [products, selectedProductId]);

  const selectedProductQuery = useQuery({
    queryKey: ["product-detail", selectedProductId],
    queryFn: async (): Promise<ProductDetail> => {
      if (!selectedProductId) {
        throw new Error("Missing selected product");
      }
      const { data } = await api.get(`/v1/products/${selectedProductId}`);
      return data;
    },
    enabled: Boolean(selectedProductId),
    refetchOnWindowFocus: false,
  });

  const inStoreMutation = useMutation({
    mutationFn: async (payload: { productId: string; inStore: boolean }) => {
      const { data } = await api.patch(`/v1/products/${payload.productId}/in-store`, {
        in_store: payload.inStore,
      });
      return data as ProductDetail;
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["product-catalog"] });
      await queryClient.invalidateQueries({ queryKey: ["product-detail", variables.productId] });
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
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Product Catalog</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Catalog, in-store status, and product detail</h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-400">
              Search, filter, and review products. Toggle in-store presence directly from the card grid or the detail drawer.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-3">
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Products</div>
              <div className="mt-1 text-2xl font-semibold text-gray-50">{totalCount.toLocaleString()}</div>
            </div>
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
        </div>
      </div>

      <div className="flex min-h-[calc(100vh-81px)] flex-col lg:flex-row">
        <aside className="w-full shrink-0 border-b border-gray-800 bg-gray-900/90 px-4 py-5 lg:w-56 lg:border-b-0 lg:border-r">
          <div className="space-y-5">
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">
                Search
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search products"
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 py-2.5 pl-9 pr-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-orange-500"
                />
              </div>
              <div className="mt-2 text-[11px] uppercase tracking-[0.2em] text-gray-500">{productsQuery.isFetching ? "Refreshing" : "300ms debounce"}</div>
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
                          setBrandIds((prev) =>
                            checked ? prev.filter((id) => id !== brand.id) : [...prev, brand.id]
                          )
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
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">
                Category
              </label>
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
            <div className="flex-1 overflow-auto px-6 py-6">
              {productsQuery.isLoading ? (
                <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
                  Loading products...
                </div>
              ) : (
            <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3">
                  {products.map((product) => {
                    const isActive = product.id === selectedProductId;
                    return (
                      <button
                        key={product.id}
                        onClick={() => setSelectedProductId(product.id)}
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
                          <label
                            className="flex items-center gap-2 text-emerald-300"
                            onClick={(event) => event.stopPropagation()}
                          >
                            <input
                              type="checkbox"
                              checked={product.in_store}
                              onChange={(event) =>
                                inStoreMutation.mutate({ productId: product.id, inStore: event.target.checked })
                              }
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
                    <div className="mt-2 text-lg font-semibold text-gray-50">
                      {activeProduct?.name || activeSummary?.name || "Loading..."}
                    </div>
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
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 p-4 text-sm text-gray-400">
                      Loading product detail...
                    </div>
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
                              onChange={(event) =>
                                inStoreMutation.mutate({ productId: activeProduct.id, inStore: event.target.checked })
                              }
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
                                      <div className="flex h-full items-center justify-center text-[11px] text-gray-500">
                                        No thumb
                                      </div>
                                    )}
                                  </div>
                                  <div className="min-w-0 flex-1">
                                    <div
                                      className="text-sm font-medium text-gray-100"
                                      style={{
                                        display: "-webkit-box",
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: "vertical",
                                        overflow: "hidden",
                                      }}
                                    >
                                      {video.title || "Untitled video"}
                                    </div>
                                    <div className="mt-1 text-xs text-gray-500">
                                      {video.original_filename || "Unknown source"}
                                    </div>
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
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 p-4 text-sm text-gray-400">
                      Select a product to open the detail drawer.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
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
      <div className="mt-1 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-100">
        {value}
      </div>
    </div>
  );
}

function EmptyNote({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-gray-800 px-3 py-6 text-center text-sm text-gray-500">{text}</div>;
}
