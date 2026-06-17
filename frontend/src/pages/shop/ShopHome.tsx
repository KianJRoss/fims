import { Link } from "react-router-dom";
import { Clock, MapPin, Phone, Sparkles, Star } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

type ProductSummary = {
  id: string;
  name: string;
  item_number: string | null;
  category_name: string | null;
  brand_name: string | null;
  in_store: boolean;
};

type DealRecord = {
  id: number;
  name: string;
  deal_type: string;
  is_active: boolean;
  notes: string | null;
  priority: number;
};

const categories = [
  "Artillery Shells",
  "500 Gram Cakes",
  "200 Gram Cakes",
  "Assortments",
  "Fountains",
  "Roman Candles",
  "Saturn Missiles",
  "Sparklers",
  "Smoke",
  "Novelties",
];

function productInitial(name: string) {
  const first = name.trim().charAt(0).toUpperCase();
  return first || "?";
}

function dealLabel(deal: DealRecord) {
  return `${deal.deal_type.replace(/_/g, " ")} deal`;
}

export default function ShopHome() {
  const productsQuery = useQuery({
    queryKey: ["shop-products-featured"],
    queryFn: async (): Promise<ProductSummary[]> => {
      const { data } = await api.get("/v1/products/", {
        params: {
          in_store: true,
          limit: 8,
          sort: "name",
        },
      });
      return data;
    },
  });

  const dealsQuery = useQuery({
    queryKey: ["shop-deals"],
    queryFn: async (): Promise<DealRecord[]> => {
      const { data } = await api.get("/v1/deals/");
      return data;
    },
  });

  const activeDeals = (dealsQuery.data ?? []).filter((deal) => deal.is_active).slice(0, 3);

  return (
    <div className="bg-white">
      <section className="relative overflow-hidden bg-gradient-to-br from-sky-500 via-sky-300 to-slate-100">
        <Sparkles className="absolute left-8 top-8 h-16 w-16 text-white/20" />
        <Star className="absolute bottom-10 right-10 h-20 w-20 text-white/20" />
        <div className="mx-auto flex min-h-[60vh] max-w-7xl items-center justify-center px-4 py-16 sm:px-6 lg:px-8">
          <div className="max-w-3xl text-center">
            <p className="text-sm font-semibold uppercase tracking-[0.35em] text-white/85">Bodigons Fireworks</p>
            <h1 className="mt-4 text-4xl font-bold tracking-tight text-white sm:text-5xl lg:text-6xl">
              Professional-grade fireworks for your biggest nights.
            </h1>
            <p className="mt-6 max-w-none text-lg text-white/90 sm:max-w-2xl sm:text-xl">
              Your local source for professional-grade fireworks, with a curated in-store selection for every kind of celebration.
            </p>
            <div className="mt-8 flex flex-wrap justify-center gap-4">
              <Link
                to="/shop/products"
                className="inline-flex items-center justify-center rounded-full bg-white px-6 py-3 text-sm font-semibold text-sky-700 shadow-sm transition hover:bg-sky-50"
              >
                Browse Products
              </Link>
              <Link
                to="/shop/map"
                className="inline-flex items-center justify-center rounded-full border border-white/60 bg-white/10 px-6 py-3 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/20"
              >
                Find Us
              </Link>
            </div>
          </div>
        </div>
      </section>

      <section className="border-y border-slate-100 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">Shop by category</h2>
              <p className="mt-1 text-sm text-slate-500">Browse the most popular firework types in our store.</p>
            </div>
          </div>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {categories.map((category) => (
              <Link
                key={category}
                to={`/shop/products?category=${encodeURIComponent(category)}`}
                className="min-w-[140px] rounded-2xl border border-slate-100 bg-white p-4 text-center shadow-sm transition hover:border-sky-300 hover:shadow-md"
              >
                <div className="text-sm font-semibold text-slate-900">{category}</div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-white">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-slate-900">Featured products</h2>
              <p className="mt-1 text-sm text-slate-500">A quick look at a few in-store favorites.</p>
            </div>
            <Link to="/shop/products" className="text-sm font-medium text-sky-700 hover:text-sky-800">
              View all products
            </Link>
          </div>

          {productsQuery.isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm">
                  <div className="h-24 animate-pulse rounded-2xl bg-slate-100" />
                  <div className="mt-4 h-4 w-3/4 animate-pulse rounded bg-slate-100" />
                  <div className="mt-3 h-6 w-24 animate-pulse rounded-full bg-slate-100" />
                  <div className="mt-4 h-10 w-full animate-pulse rounded-full bg-slate-100" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {(productsQuery.data ?? []).map((product) => (
                <article key={product.id} className="overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-sm transition hover:border-sky-200 hover:shadow-md">
                  <div className="flex h-28 items-center justify-center bg-gradient-to-br from-sky-100 to-sky-50">
                    <span className="text-4xl font-bold text-sky-700/80">{productInitial(product.name)}</span>
                  </div>
                  <div className="p-4">
                    <h3 className="line-clamp-2 text-base font-semibold text-slate-900">{product.name}</h3>
                    <div className="mt-3 inline-flex rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                      {product.category_name || "Uncategorized"}
                    </div>
                    <div className="mt-4">
                      <Link
                        to={`/shop/product/${product.id}`}
                        className="inline-flex w-full items-center justify-center rounded-full bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-600"
                      >
                        View
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>

      {activeDeals.length > 0 ? (
        <section className="border-y border-slate-100 bg-slate-50">
          <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-slate-900">Current deals</h2>
              <p className="mt-1 text-sm text-slate-500">Active offers available right now.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              {activeDeals.map((deal) => (
                <article key={deal.id} className="rounded-2xl border border-slate-100 bg-white p-5 shadow-sm">
                  <div className="text-xs font-semibold uppercase tracking-[0.25em] text-sky-600">{dealLabel(deal)}</div>
                  <h3 className="mt-3 text-lg font-semibold text-slate-900">{deal.name}</h3>
                  <p className="mt-2 text-sm text-slate-500">{deal.notes || "Special pricing available in store."}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className="bg-sky-50">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-sky-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-3">
                <MapPin className="h-5 w-5 text-sky-600" />
                <div>
                  <div className="font-semibold text-slate-900">123 Main St</div>
                  <div className="text-sm text-slate-500">Bodigons Fireworks</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-sky-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-3">
                <Clock className="h-5 w-5 text-sky-600" />
                <div>
                  <div className="font-semibold text-slate-900">Mon-Sun 9am-10pm</div>
                  <div className="text-sm text-slate-500">Open daily for the season.</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-sky-200 bg-white p-5 shadow-sm">
              <div className="flex items-center gap-3">
                <Phone className="h-5 w-5 text-sky-600" />
                <div>
                  <div className="font-semibold text-slate-900">(555) 000-0000</div>
                  <div className="text-sm text-slate-500">Call for product availability.</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
