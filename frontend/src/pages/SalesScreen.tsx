import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Barcode, CheckCircle2, Loader2, Minus, PauseCircle, Plus, Search, Trash2, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { api } from "../api/client";
import { useScannerStream } from "../hooks/useScannerStream";
import ProductImage from "../components/ProductImage";

type CartItem = {
  product_id: string;
  name: string;
  quantity: number;
  unit_price: number;
  category_id: number | null;
};

type ProductSearchResult = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  category_name: string | null;
};

type PricingResponse = {
  id: string;
  name: string;
  item_number: string | null;
  category_id: number | null;
  category_name: string | null;
  prices: Array<{
    id: number;
    price_type_code: string | null;
    price_type_name: string | null;
    amount: number;
    effective_from: string;
  }>;
};

type DealSummary = {
  applied_deals: Array<{
    deal_id: number;
    name: string;
    discount_amount: number;
    reward_type: string;
  }>;
  subtotal: number;
  total_discount: number;
  total: number;
};

type SaleCreatePayload = {
  items: Array<{
    product_id: string;
    quantity: number;
    unit_price: number;
    discount_amount: number;
  }>;
  subtotal: number;
  total_discount: number;
  total: number;
  payment_method: string;
  applied_deal_ids: number[];
};

const EMPTY_DEAL_SUMMARY: DealSummary = {
  applied_deals: [],
  subtotal: 0,
  total_discount: 0,
  total: 0,
};

type ParkedCart = {
  id: string;
  label: string;
  cart: CartItem[];
  dealSummary: DealSummary;
  parkedAt: number;
};

const PARKED_CARTS_STORAGE_KEY = "fims_parked_carts";

function loadParkedCarts(): ParkedCart[] {
  try {
    const raw = window.localStorage.getItem(PARKED_CARTS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as ParkedCart[]) : [];
  } catch {
    return [];
  }
}

function formatMoney(value: number) {
  return `$${value.toFixed(2)}`;
}

function findRetailPrice(payload: PricingResponse) {
  return payload.prices.find((price) => price.price_type_code === "RETAIL")?.amount ?? 0;
}

function findBarcodeList(barcodes: Array<{ barcode: string; barcode_type: string; is_primary: boolean }>) {
  return [...barcodes].sort((left, right) => Number(right.is_primary) - Number(left.is_primary));
}

function buildSaleItems(cart: CartItem[], totalDiscount: number) {
  const subtotal = cart.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);
  let remainingDiscount = Math.min(Math.max(totalDiscount, 0), subtotal);
  let remainingBase = subtotal;

  return cart.map((item, index) => {
    const lineSubtotal = item.quantity * item.unit_price;
    let discount = 0;

    if (remainingDiscount > 0 && lineSubtotal > 0) {
      if (index === cart.length - 1 || remainingBase <= 0) {
        discount = remainingDiscount;
      } else {
        discount = Math.min(remainingDiscount, (remainingDiscount * lineSubtotal) / remainingBase);
      }
    }

    discount = Math.min(discount, lineSubtotal);
    discount = Math.round(discount * 100) / 100;
    remainingDiscount = Math.max(0, Math.round((remainingDiscount - discount) * 100) / 100);
    remainingBase = Math.max(0, remainingBase - lineSubtotal);

    return {
      product_id: item.product_id,
      quantity: item.quantity,
      unit_price: item.unit_price,
      discount_amount: discount,
    };
  });
}

export default function SalesScreen() {
  const queryClient = useQueryClient();
  const barcodeInputRef = useRef<HTMLInputElement>(null);
  const [barcodeInput, setBarcodeInput] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [cart, setCart] = useState<CartItem[]>([]);
  const [dealSummary, setDealSummary] = useState<DealSummary>(EMPTY_DEAL_SUMMARY);
  const [expandedProductId, setExpandedProductId] = useState<string | null>(null);
  const [paymentMethod, setPaymentMethod] = useState("CASH");
  const [flash, setFlash] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [completedReceiptToken, setCompletedReceiptToken] = useState<string | null>(null);
  const [parkedCarts, setParkedCarts] = useState<ParkedCart[]>(loadParkedCarts);
  const [showParkedList, setShowParkedList] = useState(false);
  const dealRequestId = useRef(0);

  useEffect(() => {
    window.localStorage.setItem(PARKED_CARTS_STORAGE_KEY, JSON.stringify(parkedCarts));
  }, [parkedCarts]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(searchInput.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  useEffect(() => {
    barcodeInputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!flash) {
      return;
    }
    const timer = window.setTimeout(() => setFlash(null), 2500);
    return () => window.clearTimeout(timer);
  }, [flash]);

  const hasZeroPrice = cart.some((item) => item.unit_price === 0);
  const receiptBase = import.meta.env.VITE_RECEIPT_BASE_URL || window.location.origin;
  const receiptUrl = `${receiptBase}/receipt/${completedReceiptToken}`;

  const searchResultsQuery = useQuery({
    queryKey: ["sales-search", debouncedSearch],
    queryFn: async (): Promise<ProductSearchResult[]> => {
      const { data } = await api.get(`/v1/products/?q=${encodeURIComponent(debouncedSearch)}&limit=20`);
      return data;
    },
    enabled: debouncedSearch.length > 0,
  });

  const applyDealsMutation = useMutation({
    mutationFn: async (payload: { items: CartItem[]; requestId: number }) => {
      const { data } = await api.post("/v1/deals/apply", {
        items: payload.items.map((item) => ({
          product_id: item.product_id,
          quantity: item.quantity,
          unit_price: item.unit_price,
          category_id: item.category_id,
        })),
      });
      return { requestId: payload.requestId, summary: data as DealSummary };
    },
    onSuccess: ({ requestId, summary }) => {
      if (requestId !== dealRequestId.current) {
        return;
      }
      setDealSummary(summary);
    },
  });

  const saleMutation = useMutation({
    mutationFn: async (payload: SaleCreatePayload) => {
      const { data } = await api.post("/v1/sales/", payload);
      return data;
    },
    onSuccess: async (data) => {
      setCart([]);
      setDealSummary(EMPTY_DEAL_SUMMARY);
      setBarcodeInput("");
      setCompletedReceiptToken(data.receipt_token ?? null);
      barcodeInputRef.current?.focus();
      await queryClient.invalidateQueries({ queryKey: ["sales"] });
    },
    onError: () => {
      setFlash({ kind: "error", text: "Charge failed." });
    },
  });

  useEffect(() => {
    if (cart.length === 0) {
      dealRequestId.current += 1;
      setDealSummary(EMPTY_DEAL_SUMMARY);
      return;
    }

    const requestId = dealRequestId.current + 1;
    dealRequestId.current = requestId;
    applyDealsMutation.mutate({ items: cart, requestId });
  }, [cart]);

  const subtotal = useMemo(
    () => cart.reduce((sum, item) => sum + item.quantity * item.unit_price, 0),
    [cart]
  );

  const displayedDealSummary = applyDealsMutation.isPending && cart.length > 0 ? EMPTY_DEAL_SUMMARY : dealSummary;
  const totalDiscount = displayedDealSummary.total_discount;
  const total = applyDealsMutation.isPending && cart.length > 0 ? subtotal : displayedDealSummary.total;

  const addProductToCart = useCallback(async (productId: string) => {
    try {
      const { data } = await api.get<PricingResponse>(`/v1/pricing/${productId}`);
      const retailPrice = findRetailPrice(data);
      const categoryId = data.category_id ?? null;
      const name = data.name;

      setCart((current) => {
        const existingIndex = current.findIndex((item) => item.product_id === productId);
        if (existingIndex >= 0) {
          return current.map((item, index) =>
            index === existingIndex
              ? {
                  ...item,
                  quantity: item.quantity + 1,
                  unit_price: retailPrice,
                  category_id: categoryId,
                }
              : item
          );
        }
        return [...current, { product_id: productId, name, quantity: 1, unit_price: retailPrice, category_id: categoryId }];
      });
      void api.post("/v1/video-library/player/play", { product_id: productId }).catch(() => {});
      barcodeInputRef.current?.focus();
    } catch {
      setFlash({ kind: "error", text: "Product price not found." });
    }
  }, []);

  const processBarcode = useCallback(
    async (code: string) => {
      const barcode = code.trim();
      if (!barcode) {
        return;
      }
      try {
        const { data } = await api.get<ProductSearchResult[]>(`/v1/products/lookup/barcode/${encodeURIComponent(barcode)}`);
        if (!data.length) {
          throw new Error("No product");
        }
        await addProductToCart(data[0].id);
      } catch {
        setFlash({ kind: "error", text: "Barcode not found." });
      }
    },
    [addProductToCart]
  );

  useScannerStream(processBarcode);

  const handleBarcodeSubmit = useCallback(
    async (event: KeyboardEvent<HTMLInputElement>) => {
      if (event.key !== "Enter") {
        return;
      }
      event.preventDefault();
      await processBarcode(barcodeInput);
      setBarcodeInput("");
      barcodeInputRef.current?.focus();
    },
    [barcodeInput, processBarcode]
  );

  function updateCartQuantity(productId: string, delta: number) {
    setCart((current) =>
      current
        .map((item) =>
          item.product_id === productId ? { ...item, quantity: item.quantity + delta } : item
        )
        .filter((item) => item.quantity > 0)
    );
  }

  function removeFromCart(productId: string) {
    setCart((current) => current.filter((item) => item.product_id !== productId));
  }

  function clearCart() {
    setCart([]);
    setDealSummary(EMPTY_DEAL_SUMMARY);
    setBarcodeInput("");
    barcodeInputRef.current?.focus();
  }

  function parkCart() {
    if (cart.length === 0) {
      return;
    }
    const itemCount = cart.reduce((sum, item) => sum + item.quantity, 0);
    const parked: ParkedCart = {
      id: crypto.randomUUID(),
      label: `${itemCount} item${itemCount === 1 ? "" : "s"} · ${formatMoney(subtotal)}`,
      cart,
      dealSummary,
      parkedAt: Date.now(),
    };
    setParkedCarts((current) => [...current, parked]);
    setCart([]);
    setDealSummary(EMPTY_DEAL_SUMMARY);
    setBarcodeInput("");
    setFlash({ kind: "success", text: "Transaction parked." });
    barcodeInputRef.current?.focus();
  }

  function recallParkedCart(id: string) {
    if (cart.length > 0) {
      setFlash({ kind: "error", text: "Park or clear the current cart before recalling another." });
      return;
    }
    const parked = parkedCarts.find((entry) => entry.id === id);
    if (!parked) {
      return;
    }
    setCart(parked.cart);
    setDealSummary(parked.dealSummary);
    setParkedCarts((current) => current.filter((entry) => entry.id !== id));
    setShowParkedList(false);
    barcodeInputRef.current?.focus();
  }

  function deleteParkedCart(id: string) {
    setParkedCarts((current) => current.filter((entry) => entry.id !== id));
  }

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Sales</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Checkout and deal engine</h1>
            <p className="mt-2 max-w-3xl text-sm text-gray-400">
              Scan barcodes, search products, apply active deals automatically, and charge the order in one flow.
            </p>
          </div>
          <div className="flex flex-col items-start gap-3 sm:items-end">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <Metric label="Subtotal" value={formatMoney(subtotal)} />
              <Metric label="Discount" value={`-${formatMoney(totalDiscount)}`} tone="text-red-300" />
              <Metric label="Total" value={formatMoney(total)} tone="text-orange-300" />
            </div>
            {parkedCarts.length > 0 && (
              <button
                onClick={() => setShowParkedList((current) => !current)}
                className="inline-flex items-center gap-2 rounded-2xl border border-orange-500/30 bg-orange-500/10 px-4 py-2 text-sm font-medium text-orange-200 transition hover:bg-orange-500/20"
              >
                <PauseCircle className="h-4 w-4" />
                Parked ({parkedCarts.length})
              </button>
            )}
          </div>
        </div>
      </div>

      {showParkedList && parkedCarts.length > 0 && (
        <div className="mx-4 mt-4 rounded-2xl border border-gray-800 bg-gray-900 p-4 sm:mx-6">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Parked Transactions</div>
            <button onClick={() => setShowParkedList(false)} className="text-gray-500 hover:text-gray-300">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="space-y-2">
            {parkedCarts.map((parked) => (
              <div
                key={parked.id}
                className="flex items-center justify-between gap-3 rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3"
              >
                <div>
                  <div className="text-sm font-medium text-gray-100">{parked.label}</div>
                  <div className="mt-1 text-xs text-gray-500">
                    Parked {new Date(parked.parkedAt).toLocaleTimeString()}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => recallParkedCart(parked.id)}
                    className="rounded-xl border border-orange-500/30 bg-orange-500/10 px-3 py-2 text-xs font-semibold text-orange-200 transition hover:bg-orange-500/20"
                  >
                    Recall
                  </button>
                  <button
                    onClick={() => deleteParkedCart(parked.id)}
                    className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {flash && (
        <div
          className={`mx-4 mt-4 rounded-2xl border px-4 py-3 text-sm sm:mx-6 ${
            flash.kind === "success"
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
              : "border-red-500/30 bg-red-500/10 text-red-200"
          }`}
        >
          {flash.text}
        </div>
      )}

      <div className="grid min-h-[calc(100vh-145px)] grid-cols-1 gap-4 px-4 py-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)] xl:gap-0 xl:px-0 xl:py-0">
        <section className="bg-gray-900/40 px-0 py-0 xl:border-r xl:border-gray-800 xl:px-5 xl:py-5">
          <div className="flex h-full flex-col gap-4">
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
              <label className="mb-2 block text-xs uppercase tracking-[0.25em] text-gray-500">Barcode Input</label>
              <input
                ref={barcodeInputRef}
                value={barcodeInput}
                onChange={(event) => setBarcodeInput(event.target.value)}
                onKeyDown={handleBarcodeSubmit}
                placeholder="Scan barcode and press Enter"
                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-orange-500"
              />
            </div>

            <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
              <div className="border-b border-gray-800 px-4 py-3">
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Cart</div>
              </div>
              <div className="hidden overflow-auto lg:block">
                <table className="min-w-full divide-y divide-gray-800 text-sm">
                  <thead className="bg-gray-950 text-xs uppercase tracking-[0.2em] text-gray-500">
                    <tr>
                      <th className="px-4 py-3 text-left">Name</th>
                      <th className="px-4 py-3 text-left">Qty</th>
                      <th className="px-4 py-3 text-right">Unit Price</th>
                      <th className="px-4 py-3 text-right">Deal</th>
                      <th className="px-4 py-3 text-right">Line Total</th>
                      <th className="px-4 py-3 text-right">Remove</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {cart.map((item) => {
                      const lineTotal = item.quantity * item.unit_price;
                      return (
                        <tr key={item.product_id} className="hover:bg-gray-800/40">
                          <td className="px-4 py-3 align-middle">
                            <div className="font-medium text-gray-50">{item.name}</div>
                            <div className="mt-1 text-xs text-gray-500">{item.product_id}</div>
                          </td>
                          <td className="px-4 py-3 align-middle">
                            <div className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-2 py-1">
                              <button
                                onClick={() => updateCartQuantity(item.product_id, -1)}
                                className="rounded-lg p-1 text-gray-300 transition hover:bg-gray-800 hover:text-gray-50"
                              >
                                <Minus className="h-3.5 w-3.5" />
                              </button>
                              <span className="min-w-6 text-center text-sm text-gray-100">{item.quantity}</span>
                              <button
                                onClick={() => updateCartQuantity(item.product_id, 1)}
                                className="rounded-lg p-1 text-gray-300 transition hover:bg-gray-800 hover:text-gray-50"
                              >
                                <Plus className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                          <td className="px-4 py-3 align-middle text-right text-emerald-300">
                            {formatMoney(item.unit_price)}
                          </td>
                          <td className="px-4 py-3 align-middle text-right">
                            {displayedDealSummary.total_discount > 0 ? (
                              <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2.5 py-1 text-xs text-orange-200">
                                Deal
                              </span>
                            ) : (
                              <span className="text-gray-500">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 align-middle text-right text-gray-100">{formatMoney(lineTotal)}</td>
                          <td className="px-4 py-3 align-middle text-right">
                            <button
                              onClick={() => removeFromCart(item.product_id)}
                              className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                    {cart.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-16 text-center text-sm text-gray-500">
                          Scan products or add them from search.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="space-y-3 p-3 lg:hidden">
                {cart.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-4 py-10 text-center text-sm text-gray-500">
                    Scan products or add them from search.
                  </div>
                ) : (
                  cart.map((item) => {
                    const lineTotal = item.quantity * item.unit_price;
                    return (
                      <div key={item.product_id} className="rounded-2xl border border-gray-800 bg-gray-950 p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-base font-medium text-gray-50">{item.name}</div>
                            <div className="mt-1 text-xs text-gray-500">{item.product_id}</div>
                          </div>
                          <button
                            onClick={() => removeFromCart(item.product_id)}
                            className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>

                        <div className="mt-4 grid gap-3 sm:grid-cols-2">
                          <div className="space-y-2">
                            <div className="text-xs uppercase tracking-[0.2em] text-gray-500">Qty</div>
                            <div className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-900 px-2 py-1">
                              <button
                                onClick={() => updateCartQuantity(item.product_id, -1)}
                                className="rounded-lg p-2 text-gray-300 transition hover:bg-gray-800 hover:text-gray-50"
                              >
                                <Minus className="h-3.5 w-3.5" />
                              </button>
                              <span className="min-w-6 text-center text-sm text-gray-100">{item.quantity}</span>
                              <button
                                onClick={() => updateCartQuantity(item.product_id, 1)}
                                className="rounded-lg p-2 text-gray-300 transition hover:bg-gray-800 hover:text-gray-50"
                              >
                                <Plus className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>

                          <div className="grid grid-cols-2 gap-3 text-sm">
                            <div className="rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Unit</div>
                              <div className="mt-1 text-emerald-300">{formatMoney(item.unit_price)}</div>
                            </div>
                            <div className="rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Deal</div>
                              <div className="mt-1 text-gray-300">
                                {displayedDealSummary.total_discount > 0 ? "Applied" : "—"}
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2">
                          <span className="text-sm text-gray-400">Line total</span>
                          <span className="text-sm font-semibold text-gray-100">{formatMoney(lineTotal)}</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Applied Deals</div>
              <div className="mt-3 space-y-2">
                {displayedDealSummary.applied_deals.length > 0 ? (
                  displayedDealSummary.applied_deals.map((deal) => (
                    <div
                      key={deal.deal_id}
                      className="flex items-center justify-between rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5"
                    >
                      <div>
                        <div className="font-medium text-gray-50">{deal.name}</div>
                        <div className="mt-1 text-xs text-gray-500">{deal.reward_type}</div>
                      </div>
                      <div className="text-sm font-semibold text-emerald-300">-{formatMoney(deal.discount_amount)}</div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-3 py-4 text-sm text-gray-500">
                    No active deal applied.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div className="space-y-2">
                  <div className="text-sm text-gray-400">
                    Subtotal <span className="ml-2 text-gray-100">{formatMoney(subtotal)}</span>
                  </div>
                  <div className="text-sm text-red-300">
                    Total Discount <span className="ml-2 font-semibold">{formatMoney(totalDiscount)}</span>
                  </div>
                  <div className="text-3xl font-semibold text-orange-300">{formatMoney(total)}</div>
                </div>

                <div className="flex flex-col gap-3">
                  <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Payment Method</div>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {[
                      { value: "CARD", label: "Credit / Debit" },
                      { value: "CASH", label: "Cash / Check" },
                    ].map(({ value, label }) => (
                      <button
                        key={value}
                        type="button"
                        onClick={() => setPaymentMethod(value)}
                        className={`rounded-2xl border px-3 py-3 text-sm font-semibold transition ${
                          paymentMethod === value
                            ? "border-orange-500 bg-orange-500 text-white"
                            : "border-gray-700 bg-gray-800 text-gray-300 hover:border-gray-600"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  {hasZeroPrice ? (
                    <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                      One or more items have no price set. Add prices before charging.
                    </div>
                  ) : null}

                  <button
                    onClick={() =>
                      saleMutation.mutate({
                        items: buildSaleItems(cart, totalDiscount),
                        subtotal,
                        total_discount: totalDiscount,
                        total,
                        payment_method: paymentMethod,
                        applied_deal_ids: displayedDealSummary.applied_deals.map((deal) => deal.deal_id),
                      })
                    }
                    disabled={cart.length === 0 || saleMutation.isPending || applyDealsMutation.isPending || hasZeroPrice}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl bg-orange-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                  >
                    {saleMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    {applyDealsMutation.isPending ? "Applying Deals..." : "Charge"}
                  </button>

                  <button
                    onClick={parkCart}
                    disabled={cart.length === 0}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-5 py-3 text-sm text-gray-300 transition hover:border-gray-700 hover:text-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <PauseCircle className="h-4 w-4" />
                    Park Sale
                  </button>

                  <button
                    onClick={clearCart}
                    className="rounded-2xl border border-gray-800 bg-gray-950 px-5 py-3 text-sm text-gray-300 transition hover:border-gray-700 hover:text-gray-100"
                  >
                    Clear Cart
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <aside className="bg-gray-900/30 px-0 py-0 xl:px-5 xl:py-5">
          <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
            <div className="flex items-center gap-3">
              <Search className="h-4 w-4 text-gray-500" />
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search products"
                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none placeholder:text-gray-600 focus:border-orange-500"
              />
            </div>
          </div>

          <div className="mt-4 space-y-3">
            {searchResultsQuery.isFetching && debouncedSearch.length > 0 && (
              <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4 text-sm text-gray-400">
                Loading products...
              </div>
            )}

            {debouncedSearch.length === 0 ? (
              <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-8 text-center text-sm text-gray-500">
                Search products by name or item number.
              </div>
            ) : (
              (searchResultsQuery.data ?? []).map((product) => (
                <SearchResultCard
                  key={product.id}
                  product={product}
                  expanded={expandedProductId === product.id}
                  onToggleExpanded={() =>
                    setExpandedProductId((current) => (current === product.id ? null : product.id))
                  }
                  onAdd={() => void addProductToCart(product.id)}
                />
              ))
            )}

            {debouncedSearch.length > 0 && searchResultsQuery.data?.length === 0 && (
              <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-8 text-center text-sm text-gray-500">
                No products found.
              </div>
            )}
          </div>
        </aside>
      </div>

      {completedReceiptToken !== null ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-3xl border border-gray-800 bg-gray-900 p-8 text-center shadow-2xl">
            <div className="flex items-center justify-center gap-2 text-2xl font-semibold text-gray-50">
              <CheckCircle2 className="h-7 w-7 text-emerald-400" />
              Sale Complete
            </div>
            <div className="mt-6 flex justify-center">
              <QRCodeSVG value={receiptUrl} size={200} bgColor="#111827" fgColor="#f97316" level="M" />
            </div>
            <div className="mt-4 text-sm text-gray-400">Scan for digital receipt</div>
            <div className="mt-2 font-mono text-xs text-gray-500">{completedReceiptToken}</div>
            <button
              type="button"
              onClick={() => {
                setCompletedReceiptToken(null);
                barcodeInputRef.current?.focus();
              }}
              className="mt-4 w-full rounded-2xl bg-orange-500 py-3 font-semibold text-white transition hover:bg-orange-400"
            >
              Done
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Metric({ label, value, tone = "text-gray-100" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 px-4 py-3">
      <div className="text-xs uppercase tracking-[0.25em] text-gray-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function SearchResultCard({
  product,
  expanded,
  onToggleExpanded,
  onAdd,
}: {
  product: ProductSearchResult;
  expanded: boolean;
  onToggleExpanded: () => void;
  onAdd: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["search-product-detail", product.id],
    queryFn: async () => {
      const { data } = await api.get(`/v1/products/${product.id}`);
      return data as {
        barcodes: Array<{ id: number; barcode: string; barcode_type: string; is_primary: boolean }>;
      };
    },
    enabled: expanded,
  });

  const pricingQuery = useQuery({
    queryKey: ["search-product-pricing", product.id],
    queryFn: async () => {
      const { data } = await api.get<PricingResponse>(`/v1/pricing/${product.id}`);
      return {
        retailPrice: findRetailPrice(data),
      };
    },
  });

  return (
      <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
      <div
        onClick={onAdd}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onAdd();
          }
        }}
        className="block w-full cursor-pointer px-4 py-4 text-left transition hover:bg-gray-800/60"
      >
        <div className="flex items-start justify-between gap-3">
          <ProductImage imageUrl={product.image_url} name={product.name} size="xs" className="mt-0.5" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-base font-semibold text-gray-50">{product.name}</div>
            <div className="mt-1 text-xs text-gray-500">{product.item_number || "No item number"}</div>
          </div>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onToggleExpanded();
            }}
            className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-300 transition hover:border-gray-700 hover:text-gray-50"
          >
            <Barcode className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-xs text-gray-300">
            {product.category_name || "No category"}
          </span>
          <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2.5 py-1 text-xs text-orange-200">
            {pricingQuery.isError
              ? "No retail price"
              : pricingQuery.data
                ? formatMoney(pricingQuery.data.retailPrice)
                : "Loading price..."}
          </span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-800 bg-gray-950 px-4 py-3">
          <div className="text-[11px] uppercase tracking-[0.25em] text-gray-500">Barcodes</div>
          <div className="mt-2 space-y-2">
            {detailQuery.data?.barcodes?.length ? (
              findBarcodeList(detailQuery.data.barcodes).map((barcode) => (
                <div
                  key={barcode.barcode}
                  className="flex items-center justify-between rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm"
                >
                  <span className="font-mono text-gray-100">{barcode.barcode}</span>
                  <span className="text-xs text-gray-500">
                    {barcode.is_primary ? "Primary" : barcode.barcode_type}
                  </span>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-900 px-3 py-4 text-sm text-gray-500">
                {detailQuery.isLoading ? "Loading barcodes..." : "No barcodes on file."}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
