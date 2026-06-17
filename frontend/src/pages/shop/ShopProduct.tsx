import { Link, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

type ProductVideo = {
  id: number;
  youtube_id: string | null;
  confirmed: boolean;
  thumbnail_url: string | null;
  title: string | null;
  duration_seconds: number | null;
};

type ProductDetail = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  category_name: string | null;
  brand_name: string | null;
  shot_count: number | null;
  duration_seconds: number | null;
  effects: string | null;
  videos: ProductVideo[];
};

type PricingResponse = {
  id: string;
  name: string;
  prices: Array<{
    id: number;
    price_type_code: string | null;
    price_type_name: string | null;
    amount: number;
  }>;
};

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "Unavailable";
  }
  return `$${value.toFixed(2)}`;
}

export default function ShopProduct() {
  const { id } = useParams();

  const productQuery = useQuery({
    queryKey: ["shop-product", id],
    queryFn: async (): Promise<ProductDetail> => {
      if (!id) {
        throw new Error("Missing product id");
      }
      const { data } = await api.get(`/v1/products/${encodeURIComponent(id)}`);
      return data;
    },
    enabled: Boolean(id),
  });

  const pricingQuery = useQuery({
    queryKey: ["shop-pricing", id],
    queryFn: async (): Promise<PricingResponse> => {
      if (!id) {
        throw new Error("Missing product id");
      }
      const { data } = await api.get(`/v1/pricing/${encodeURIComponent(id)}`);
      return data;
    },
    enabled: Boolean(id),
  });

  const product = productQuery.data;
  const retailPrice = pricingQuery.data?.prices.find((price) => price.price_type_code === "RETAIL")?.amount ?? null;
  const confirmedVideos = product?.videos.filter((video) => video.confirmed && video.youtube_id);
  const video = confirmedVideos?.[0] ?? null;

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:px-8">
      <Link to="/shop/products" className="inline-flex items-center gap-2 text-sm font-medium text-sky-700 hover:text-sky-800">
        <ArrowLeft className="h-4 w-4" />
        Back to products
      </Link>

      <div className="mt-6 rounded-3xl border border-slate-100 bg-white p-6 shadow-sm sm:p-8">
        {productQuery.isLoading ? (
          <div className="space-y-4">
            <div className="h-8 w-2/3 animate-pulse rounded bg-slate-100" />
            <div className="h-6 w-1/3 animate-pulse rounded bg-slate-100" />
            <div className="h-64 animate-pulse rounded-2xl bg-slate-100" />
          </div>
        ) : product ? (
          <div className="space-y-8">
            <div>
              <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{product.name}</h1>
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                  {product.category_name || "Uncategorized"}
                </span>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
                  {product.brand_name || "No brand"}
                </span>
              </div>
              <div className="mt-4 text-sm text-slate-500">Item number: {product.item_number || "No item number"}</div>
            </div>

            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
              {product.image_url && (
                <div className="flex h-64 w-full flex-shrink-0 items-center justify-center rounded-2xl border border-slate-100 bg-gradient-to-br from-sky-50 to-slate-50 p-4 sm:h-64 sm:w-64">
                  <img
                    src={product.image_url}
                    alt={product.name}
                    className="max-h-full max-w-full object-contain"
                    onError={(e) => { (e.currentTarget.parentElement as HTMLElement).style.display = "none"; }}
                  />
                </div>
              )}
              <div className="flex-1">
                {video?.youtube_id ? (
                  <div className="overflow-hidden rounded-2xl border border-slate-200 bg-slate-100">
                    <div className="aspect-video w-full">
                      <iframe
                        className="h-full w-full"
                        src={`https://www.youtube.com/embed/${video.youtube_id}`}
                        title={video.title || `${product.name} video`}
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                        allowFullScreen
                      />
                    </div>
                  </div>
                ) : (
                  <div className="flex min-h-[200px] items-center justify-center rounded-2xl bg-gradient-to-br from-sky-100 to-slate-100 text-center">
                    <div>
                      <div className="text-lg font-semibold text-slate-900">No demo video available</div>
                      <div className="mt-2 text-sm text-slate-500">We do not have a confirmed product video yet.</div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">Retail</div>
                <div className="mt-2 text-2xl font-bold text-sky-600">{formatMoney(retailPrice)}</div>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">Shot count</div>
                <div className="mt-2 text-2xl font-bold text-slate-900">{product.shot_count ?? "Unknown"}</div>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">Duration</div>
                <div className="mt-2 text-2xl font-bold text-slate-900">
                  {product.duration_seconds !== null ? `${product.duration_seconds}s` : "Unknown"}
                </div>
              </div>
              <div className="rounded-2xl border border-slate-100 bg-slate-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-[0.25em] text-slate-500">Effects</div>
                <div className="mt-2 text-sm font-medium text-slate-700">{product.effects || "Not listed"}</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-slate-500">
            Product not found.
          </div>
        )}
      </div>
    </div>
  );
}
