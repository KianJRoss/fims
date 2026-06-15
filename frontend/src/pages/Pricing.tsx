import { useEffect, useMemo, useState } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Loader2, Search } from "lucide-react";

import { api } from "../api/client";

type Brand = {
  id: number;
  name: string;
};

type PricingCode = "RETAIL" | "SALE" | "WHOLE" | "COST" | "TENT";

type PricingRow = {
  id: string;
  name: string;
  item_number: string | null;
  brand_name: string | null;
  category_name: string | null;
  in_store: boolean;
  catalog_page: number | null;
  prices: Record<PricingCode, number | null>;
};

type PriceMutationInput = {
  productId: string;
  priceTypeCode: PricingCode;
  amount: number;
};

const PRICE_COLUMNS: Array<{ code: PricingCode; label: string }> = [
  { code: "RETAIL", label: "RETAIL" },
  { code: "SALE", label: "SALE" },
  { code: "WHOLE", label: "WHOLESALE" },
  { code: "COST", label: "COST" },
  { code: "TENT", label: "TENT" },
];

function formatAmount(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `$${value.toFixed(2)}`;
}

export default function Pricing() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("");
  const [selectedBrandIds, setSelectedBrandIds] = useState<number[]>([]);
  const [inStoreOnly, setInStoreOnly] = useState(false);
  const [editingCell, setEditingCell] = useState<{
    productId: string;
    priceTypeCode: PricingCode;
    value: string;
  } | null>(null);
  const [seeded, setSeeded] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const brandsQuery = useQuery({
    queryKey: ["pricing-brands"],
    queryFn: async (): Promise<Brand[]> => {
      const { data } = await api.get("/v1/brands/");
      return data;
    },
  });

  const categoriesQuery = useQuery({
    queryKey: ["pricing-categories"],
    queryFn: async (): Promise<string[]> => {
      const { data } = await api.get("/v1/products/categories");
      return data;
    },
  });

  const productsQuery = useInfiniteQuery({
    queryKey: ["pricing-products", debouncedSearch, selectedCategory, selectedBrandIds, inStoreOnly],
    queryFn: async ({ pageParam = 0 }): Promise<PricingRow[]> => {
      const params = new URLSearchParams();
      params.set("skip", String(pageParam));
      params.set("limit", "100");
      if (debouncedSearch) {
        params.set("q", debouncedSearch);
      }
      if (selectedCategory) {
        params.set("category", selectedCategory);
      }
      if (inStoreOnly) {
        params.set("in_store", "true");
      }
      for (const brandId of selectedBrandIds) {
        params.append("brand_id", String(brandId));
      }
      const { data } = await api.get(`/v1/pricing/?${params.toString()}`);
      return data;
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => (lastPage.length === 100 ? allPages.length * 100 : undefined),
  });

  const products = useMemo(
    () => productsQuery.data?.pages.flatMap((page) => page) ?? [],
    [productsQuery.data]
  );

  useEffect(() => {
    if (!editingCell) {
      return;
    }
    const stillVisible = products.some(
      (product) => product.id === editingCell.productId && product.prices[editingCell.priceTypeCode] !== undefined
    );
    if (!stillVisible) {
      setEditingCell(null);
    }
  }, [editingCell, products]);

  const seedMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post("/v1/pricing/seed-types");
      return data as { count: number };
    },
    onSuccess: async () => {
      setSeeded(true);
      await queryClient.invalidateQueries({ queryKey: ["pricing-products"] });
    },
  });

  const priceMutation = useMutation({
    mutationFn: async (payload: PriceMutationInput) => {
      const { data } = await api.put(`/v1/pricing/${payload.productId}/${payload.priceTypeCode}`, {
        amount: payload.amount,
      });
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["pricing-products"] });
    },
    onSettled: () => setEditingCell(null),
  });

  function beginEdit(productId: string, priceTypeCode: PricingCode, currentValue: number | null) {
    setEditingCell({
      productId,
      priceTypeCode,
      value: currentValue === null ? "" : String(currentValue),
    });
  }

  function updateEditingValue(event: ChangeEvent<HTMLInputElement>) {
    if (!editingCell) {
      return;
    }
    setEditingCell({ ...editingCell, value: event.target.value });
  }

  function saveEditingValue() {
    if (!editingCell) {
      return;
    }
    if (editingCell.value.trim() === "") {
      setEditingCell(null);
      return;
    }
    const parsed = Number(editingCell.value);
    if (!Number.isFinite(parsed)) {
      setEditingCell(null);
      return;
    }
    priceMutation.mutate({
      productId: editingCell.productId,
      priceTypeCode: editingCell.priceTypeCode,
      amount: parsed,
    });
  }

  function handleEditingKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.currentTarget.blur();
    }
    if (event.key === "Escape") {
      setEditingCell(null);
    }
  }

  function toggleBrand(brandId: number) {
    setSelectedBrandIds((current) =>
      current.includes(brandId) ? current.filter((id) => id !== brandId) : [...current, brandId]
    );
  }

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Pricing</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Price matrix and inline editing</h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-400">
              Search products, filter by brand or category, and edit price tiers directly in the grid.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-3">
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Loaded</div>
              <div className="mt-1 text-2xl font-semibold text-gray-50">{products.length.toLocaleString()}</div>
            </div>
            <button
              onClick={() => seedMutation.mutate()}
              disabled={seeded || seedMutation.isPending}
              className={`rounded-2xl px-4 py-3 text-sm font-semibold transition ${
                seeded
                  ? "border border-gray-700 bg-gray-800 text-gray-400"
                  : "bg-orange-500 text-white hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
              }`}
            >
              {seedMutation.isPending ? "Seeding..." : seeded ? "Price Types Seeded" : "Seed Price Types"}
            </button>
          </div>
        </div>
      </div>

      <div className="flex min-h-[calc(100vh-81px)]">
        <aside className="w-56 shrink-0 border-r border-gray-800 bg-gray-900/90 px-4 py-5">
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
            </div>

            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">Brands</div>
              <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
                {(brandsQuery.data ?? []).map((brand) => {
                  const checked = selectedBrandIds.includes(brand.id);
                  return (
                    <label
                      key={brand.id}
                      className={`flex cursor-pointer items-center justify-between rounded-xl border px-2.5 py-1.5 text-xs transition ${
                        checked
                          ? "border-orange-500/60 bg-orange-500/10 text-orange-100"
                          : "border-gray-800 bg-gray-950 text-gray-400 hover:border-gray-700 hover:text-gray-200"
                      }`}
                    >
                      <span className="truncate pr-2">{brand.name}</span>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleBrand(brand.id)}
                        className="accent-orange-500"
                      />
                    </label>
                  );
                })}
              </div>
            </div>

            <div>
              <label className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-[0.25em] text-gray-500">
                <span>Category</span>
                <ChevronDown className="h-4 w-4 text-gray-600" />
              </label>
              <select
                value={selectedCategory}
                onChange={(event) => setSelectedCategory(event.target.value)}
                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
              >
                <option value="">All categories</option>
                {(categoriesQuery.data ?? []).map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </div>

            <label className="flex cursor-pointer items-center justify-between rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-200 transition hover:border-gray-700">
              <span>In Store only</span>
              <input
                type="checkbox"
                checked={inStoreOnly}
                onChange={(event) => setInStoreOnly(event.target.checked)}
                className="accent-orange-500"
              />
            </label>
          </div>
        </aside>

        <main className="flex-1 overflow-hidden">
          <div className="flex h-full flex-col">
            <div className="flex-1 overflow-auto px-6 py-6">
              <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
                <table className="min-w-full divide-y divide-gray-800">
                  <thead className="sticky top-0 bg-gray-950">
                    <tr className="text-left text-xs uppercase tracking-[0.2em] text-gray-500">
                      <th className="px-4 py-3">Name</th>
                      <th className="px-4 py-3">Item#</th>
                      <th className="px-4 py-3">Catalog Page</th>
                      <th className="px-4 py-3">Category</th>
                      {PRICE_COLUMNS.map((column) => (
                        <th key={column.code} className="px-4 py-3 text-right">
                          {column.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {products.map((product) => (
                      <tr key={product.id} className="bg-transparent hover:bg-gray-800/40">
                        <td className="px-4 py-3 align-middle">
                          <div className="font-medium text-gray-50">{product.name}</div>
                          <div className="mt-1 text-xs text-gray-500">{product.brand_name || "No brand"}</div>
                        </td>
                        <td className="px-4 py-3 align-middle text-sm text-gray-300">{product.item_number || "—"}</td>
                        <td className="px-4 py-3 align-middle text-sm text-gray-300">
                          {product.catalog_page ?? "—"}
                        </td>
                        <td className="px-4 py-3 align-middle text-sm text-gray-300">
                          {product.category_name || "—"}
                        </td>
                        {PRICE_COLUMNS.map((column) => {
                          const currentValue = product.prices[column.code];
                          const isEditing =
                            editingCell?.productId === product.id && editingCell.priceTypeCode === column.code;

                          return (
                            <td key={column.code} className="px-4 py-3 align-middle text-right">
                              {isEditing ? (
                                <input
                                  autoFocus
                                  value={editingCell.value}
                                  onChange={updateEditingValue}
                                  onBlur={saveEditingValue}
                                  onKeyDown={handleEditingKeyDown}
                                  className="w-24 rounded-xl border border-orange-500 bg-gray-950 px-2 py-1 text-right text-sm text-gray-100 outline-none"
                                />
                              ) : (
                                <button
                                  onClick={() => beginEdit(product.id, column.code, currentValue)}
                                  className={`rounded-xl px-2 py-1 text-sm transition ${
                                    currentValue === null
                                      ? "text-gray-500 hover:bg-gray-800 hover:text-gray-200"
                                      : "font-medium text-emerald-300 hover:bg-emerald-500/10"
                                  }`}
                                >
                                  {formatAmount(currentValue)}
                                </button>
                              )}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                    {products.length === 0 && !productsQuery.isLoading && (
                      <tr>
                        <td colSpan={9} className="px-4 py-12 text-center text-sm text-gray-500">
                          No products match the current filters.
                        </td>
                      </tr>
                    )}
                    {productsQuery.isLoading && (
                      <tr>
                        <td colSpan={9} className="px-4 py-12 text-center text-sm text-gray-400">
                          Loading pricing...
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="mt-6 flex items-center justify-center">
                <button
                  onClick={() => productsQuery.fetchNextPage()}
                  disabled={!productsQuery.hasNextPage || productsQuery.isFetchingNextPage}
                  className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                >
                  {productsQuery.isFetchingNextPage ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {productsQuery.isFetchingNextPage
                    ? "Loading..."
                    : productsQuery.hasNextPage
                      ? "Load 100 More"
                      : "No More Products"}
                </button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
