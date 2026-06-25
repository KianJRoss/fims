import { Link } from "react-router-dom";
import { Clock, MapPin, Phone, Sparkles, Star } from "lucide-react";
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

function dealLabel(deal: DealRecord) {
  return `${deal.deal_type.replace(/_/g, " ")} deal`;
}

function ProductPhotoCard({ product }: { product: ProductSummary }) {
  return (
    <article className="group overflow-hidden rounded-3xl border border-white/10 bg-slate-900/80 shadow-sm transition hover:-translate-y-0.5 hover:border-sky-200 hover:shadow-xl hover:shadow-slate-950/20">
      <div className="relative h-56 overflow-hidden bg-gradient-to-br from-slate-800 via-slate-700 to-sky-950/60">
        {product.image_url ? (
          <img
            src={product.image_url}
            alt={product.name}
            className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <div className="rounded-full bg-slate-950/80 px-6 py-5 text-4xl font-semibold tracking-tight text-sky-300 shadow-sm">
              {product.name.trim().charAt(0).toUpperCase() || "?"}
            </div>
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/60 via-slate-950/0 to-transparent" />
        <div className="absolute bottom-0 left-0 right-0 p-4 text-white">
          <div className="inline-flex rounded-full bg-sky-500/15 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.25em] text-sky-100 backdrop-blur">
            {product.category_name || "Uncategorized"}
          </div>
          <h3 className="mt-3 line-clamp-2 text-lg font-semibold leading-snug">{product.name}</h3>
        </div>
      </div>
      <div className="p-4">
        <div className="text-sm text-slate-300">{product.item_number || "No item number"}</div>
        <Link
          to={`/shop/product/${product.id}`}
          className="mt-4 inline-flex w-full items-center justify-center rounded-full bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-sky-400"
        >
          View details
        </Link>
      </div>
    </article>
  );
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
  const featuredProducts = (productsQuery.data ?? []).slice(0, 8);
  const heroProduct = featuredProducts.find((product) => product.image_url) ?? featuredProducts[0] ?? null;
  const heroSecondary = featuredProducts.filter((product) => product.id !== heroProduct?.id).slice(0, 3);

  return (
    <div className="bg-slate-950 text-slate-100">
      <section className="relative overflow-hidden bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.20),_transparent_32%),linear-gradient(135deg,_#0f172a_0%,_#334155_44%,_#1d4ed8_72%,_#f8fafc_100%)]">
        <Sparkles className="absolute left-8 top-8 h-16 w-16 text-sky-200/40" />
        <Star className="absolute bottom-10 right-10 h-20 w-20 text-amber-200/40" />
        <div className="mx-auto grid min-h-[62vh] max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:px-8">
          <div className="max-w-2xl">
            <p className="text-sm font-semibold uppercase tracking-[0.35em] text-sky-200">Bodigon Fireworks</p>
            <h1 className="mt-4 text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-6xl">
              Professional-grade fireworks for your biggest nights.
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-slate-200 sm:text-xl">
              Your local source for professional-grade fireworks, with a curated in-store selection for every kind of celebration.
            </p>
            <div className="mt-8 flex flex-wrap gap-4">
              <Link
                to="/shop/products"
                className="inline-flex items-center justify-center rounded-full bg-white px-6 py-3 text-sm font-semibold text-slate-900 shadow-lg shadow-slate-950/20 transition hover:bg-sky-50"
              >
                Browse Products
              </Link>
              <Link
                to="/shop/map"
                className="inline-flex items-center justify-center rounded-full border border-white/20 bg-white/10 px-6 py-3 text-sm font-semibold text-white backdrop-blur transition hover:bg-white/20"
              >
                Find Us
              </Link>
            </div>
          </div>

          <div className="grid gap-4">
            {heroProduct ? (
              <article className="group overflow-hidden rounded-[2rem] border border-white/15 bg-slate-900/65 shadow-2xl shadow-slate-950/40 backdrop-blur">
                <div className="relative h-72 overflow-hidden">
                  {heroProduct.image_url ? (
                    <img
                      src={heroProduct.image_url}
                      alt={heroProduct.name}
                      className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-800 to-slate-700">
                      <div className="text-7xl font-semibold text-sky-300/90">{heroProduct.name.trim().charAt(0).toUpperCase() || "?"}</div>
                    </div>
                  )}
                  <div className="absolute inset-0 bg-gradient-to-t from-slate-950/75 via-slate-950/10 to-transparent" />
                  <div className="absolute bottom-0 left-0 right-0 p-5 text-white">
                    <div className="text-xs uppercase tracking-[0.28em] text-sky-100">Featured now</div>
                    <div className="mt-2 text-2xl font-semibold leading-tight text-white">{heroProduct.name}</div>
                    <div className="mt-2 text-sm text-sky-50/90">{heroProduct.category_name || "Uncategorized"}</div>
                  </div>
                </div>
              </article>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              {heroSecondary.map((product) => (
                <article key={product.id} className="flex overflow-hidden rounded-[1.75rem] border border-white/10 bg-slate-900/70 shadow-xl shadow-slate-950/25 backdrop-blur">
                  <div className="h-28 w-28 flex-shrink-0 overflow-hidden bg-slate-100 sm:h-32 sm:w-32">
                    {product.image_url ? (
                      <img src={product.image_url} alt={product.name} className="h-full w-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-slate-800 to-slate-700 text-3xl font-semibold text-sky-300/80">
                        {product.name.trim().charAt(0).toUpperCase() || "?"}
                      </div>
                    )}
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col justify-between p-4">
                    <div>
                      <div className="text-xs uppercase tracking-[0.25em] text-slate-400">In store</div>
                      <div className="mt-2 line-clamp-2 text-base font-semibold text-white">{product.name}</div>
                      <div className="mt-1 text-sm text-slate-300">{product.category_name || "Uncategorized"}</div>
                    </div>
                    <Link to={`/shop/product/${product.id}`} className="mt-3 text-sm font-semibold text-sky-300 hover:text-sky-200">
                      View product
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="border-y border-white/10 bg-slate-900/80">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-white">Shop by category</h2>
              <p className="mt-1 text-sm text-slate-300">Browse the most popular firework types in our store.</p>
            </div>
          </div>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {categories.map((category) => (
              <Link
                key={category}
                to={`/shop/products?category=${encodeURIComponent(category)}`}
                className="min-w-[140px] rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-center text-slate-100 shadow-sm transition hover:border-sky-300 hover:bg-slate-900"
              >
                <div className="text-sm font-semibold text-slate-100">{category}</div>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <section className="bg-slate-950">
        <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
          <div className="mb-6 flex items-end justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-white">Featured products</h2>
              <p className="mt-1 text-sm text-slate-300">A quick look at a few in-store favorites.</p>
            </div>
            <Link to="/shop/products" className="text-sm font-medium text-sky-300 hover:text-sky-200">
              View all products
            </Link>
          </div>

          {productsQuery.isLoading ? (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {Array.from({ length: 8 }).map((_, index) => (
                <div key={index} className="rounded-2xl border border-white/10 bg-slate-900 p-4 shadow-sm">
                  <div className="h-24 animate-pulse rounded-2xl bg-slate-800" />
                  <div className="mt-4 h-4 w-3/4 animate-pulse rounded bg-slate-800" />
                  <div className="mt-3 h-6 w-24 animate-pulse rounded-full bg-slate-800" />
                  <div className="mt-4 h-10 w-full animate-pulse rounded-full bg-slate-800" />
                </div>
              ))}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {featuredProducts.map((product) => (
                <ProductPhotoCard key={product.id} product={product} />
              ))}
            </div>
          )}
        </div>
      </section>

      {activeDeals.length > 0 ? (
        <section className="border-y border-white/10 bg-slate-900/85">
          <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-white">Current deals</h2>
              <p className="mt-1 text-sm text-slate-300">Active offers available right now.</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              {activeDeals.map((deal) => (
                <article key={deal.id} className="rounded-2xl border border-white/10 bg-slate-950/70 p-5 shadow-sm">
                  <div className="text-xs font-semibold uppercase tracking-[0.25em] text-sky-300">{dealLabel(deal)}</div>
                  <h3 className="mt-3 text-lg font-semibold text-white">{deal.name}</h3>
                  <p className="mt-2 text-sm text-slate-300">{deal.notes || "Special pricing available in store."}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className="bg-[linear-gradient(180deg,_#334155_0%,_#475569_36%,_#93c5fd_100%)]">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-white/20 bg-slate-950/70 p-5 shadow-lg shadow-slate-950/20">
              <div className="flex items-center gap-3">
                <MapPin className="h-5 w-5 text-sky-300" />
                <div>
                  <div className="font-semibold text-white">2740 US-6, Kendallville, IN 46755, USA</div>
                  <div className="text-sm text-slate-300">Bodigon Fireworks</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-white/20 bg-slate-950/70 p-5 shadow-lg shadow-slate-950/20">
              <div className="flex items-center gap-3">
                <Clock className="h-5 w-5 text-sky-300" />
                <div>
                  <div className="font-semibold text-white">9 AM to 7 PM, likely later</div>
                  <div className="text-sm text-slate-300">Expect 10 PM hours for the 2nd through the 5th.</div>
                </div>
              </div>
            </div>
            <div className="rounded-2xl border border-white/20 bg-slate-950/70 p-5 shadow-lg shadow-slate-950/20">
              <div className="flex items-center gap-3">
                <Phone className="h-5 w-5 text-sky-300" />
                <div>
                  <div className="font-semibold text-white">(260) 347-8595</div>
                  <div className="text-sm text-slate-300">Call for product availability.</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
