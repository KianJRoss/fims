import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

type ProductSummary = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  category_name: string | null;
  brand_name: string | null;
  in_store: boolean;
};

function productInitial(name: string) {
  const first = name.trim().charAt(0).toUpperCase();
  return first || "?";
}

function matchesSearch(product: ProductSummary, search: string) {
  if (!search) return true;
  const haystack = [product.name, product.item_number, product.category_name, product.brand_name]
    .filter((value): value is string => Boolean(value))
    .join(" ")
    .toLowerCase();
  return haystack.includes(search.toLowerCase());
}

export default function ShopProducts() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const categoryParam = searchParams.get("category") ?? "";
  const [selectedCategory, setSelectedCategory] = useState(categoryParam);

  useEffect(() => {
    setSelectedCategory(categoryParam);
  }, [categoryParam]);

  const productsQuery = useQuery({
    queryKey: ["shop-products", "catalog"],
    queryFn: async (): Promise<ProductSummary[]> => {
      const { data } = await api.get("/v1/products/", {
        params: {
          in_store: true,
          limit: 200,
        },
      });
      return data;
    },
  });

  const categories = Array.from(
    new Set((productsQuery.data ?? []).map((product) => product.category_name).filter((value): value is string => Boolean(value)))
  ).sort((left, right) => left.localeCompare(right));

  const filteredProducts = (productsQuery.data ?? []).filter((product) => {
    const categoryMatch = selectedCategory ? product.category_name === selectedCategory : true;
    return categoryMatch && matchesSearch(product, search.trim());
  });

  function updateCategory(category: string) {
    setSelectedCategory(category);
    if (category) {
      setSearchParams({ category });
    } else {
      setSearchParams({});
    }
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-10 text-slate-100 sm:px-6 lg:px-8">
      <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-white">Products</h1>
          <p className="mt-2 text-sm text-slate-300">
            {filteredProducts.length} of {(productsQuery.data ?? []).length} products shown
          </p>
        </div>
        <div className="w-full max-w-md">
          <label className="mb-2 block text-sm font-medium text-slate-200">Search products</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by name, item number, brand, or category"
              className="w-full rounded-2xl border border-white/10 bg-slate-900/80 py-3 pl-10 pr-4 text-sm text-white shadow-sm outline-none transition placeholder:text-slate-400 focus:border-sky-300 focus:ring-4 focus:ring-sky-950/40"
            />
          </div>
        </div>
      </div>

      <div className="mb-8">
        <div className="mb-3 text-sm font-medium text-slate-200">Categories</div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => updateCategory("")}
            className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
              selectedCategory
                ? "border-white/10 bg-slate-900/70 text-slate-300 hover:border-sky-200 hover:text-white"
                : "border-sky-200 bg-sky-500 text-white"
            }`}
          >
            All
          </button>
          {categories.map((category) => {
            const active = selectedCategory === category;
            return (
              <button
                type="button"
                key={category}
                onClick={() => updateCategory(category)}
                className={`rounded-full border px-4 py-2 text-sm font-medium transition ${
                  active
                    ? "border-sky-200 bg-sky-500 text-white"
                    : "border-white/10 bg-slate-900/70 text-slate-300 hover:border-sky-200 hover:text-white"
                }`}
              >
                {category}
              </button>
            );
          })}
        </div>
      </div>

      {productsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="rounded-2xl border border-white/10 bg-slate-900/80 p-4 shadow-sm">
              <div className="h-28 animate-pulse rounded-2xl bg-slate-800" />
              <div className="mt-4 h-4 w-3/4 animate-pulse rounded bg-slate-800" />
              <div className="mt-3 h-3 w-1/2 animate-pulse rounded bg-slate-800" />
              <div className="mt-4 h-10 w-full animate-pulse rounded-full bg-slate-800" />
            </div>
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filteredProducts.map((product) => (
            <article key={product.id} className="overflow-hidden rounded-2xl border border-white/10 bg-slate-900/80 shadow-sm transition hover:border-sky-200 hover:shadow-lg hover:shadow-slate-950/20">
              <div className="flex h-40 items-center justify-center overflow-hidden bg-gradient-to-br from-slate-800 via-slate-700 to-sky-900/60">
                {product.image_url ? (
                  <img
                    src={product.image_url}
                    alt={product.name}
                    className="h-full w-full object-contain p-2"
                    onError={(e) => {
                      const target = e.currentTarget;
                      target.style.display = "none";
                      const fallback = target.nextElementSibling as HTMLElement | null;
                      if (fallback) fallback.style.display = "flex";
                    }}
                  />
                ) : null}
                <span
                  className="text-4xl font-bold text-sky-300/80"
                  style={{ display: product.image_url ? "none" : "flex" }}
                >
                  {productInitial(product.name)}
                </span>
              </div>
              <div className="p-4">
                <h2 className="line-clamp-2 text-base font-semibold text-white">{product.name}</h2>
                <div className="mt-2 text-sm text-slate-300">{product.item_number || "No item number"}</div>
                <div className="mt-3 inline-flex rounded-full border border-sky-300/20 bg-sky-500/10 px-3 py-1 text-xs font-medium text-sky-200">
                  {product.category_name || "Uncategorized"}
                </div>
                <div className="mt-4">
                  <Link
                    to={`/shop/product/${product.id}`}
                    className="inline-flex w-full items-center justify-center rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-400"
                  >
                    View Details
                  </Link>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
