import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { api } from "../api/client";

type ReceiptItem = {
  name: string;
  item_number: string | null;
  qty: number;
  unit_price: number;
  line_total: number;
};

type ReceiptResponse = {
  id: string;
  created_at: string;
  payment_method: "CARD" | "CASH";
  card_last4: string | null;
  receipt_token: string;
  subtotal: number;
  discount_total: number;
  total: number;
  store_name: string;
  items: ReceiptItem[];
};

function formatMoney(value: number) {
  return `$${value.toFixed(2)}`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatPaymentMethod(receipt: ReceiptResponse) {
  if (receipt.payment_method === "CASH") {
    return "Cash";
  }

  return `Visa/MC ****${receipt.card_last4 ?? "----"}`;
}

export default function Receipt() {
  const { token } = useParams<{ token: string }>();

  const receiptQuery = useQuery({
    queryKey: ["receipt", token],
    enabled: Boolean(token),
    queryFn: async (): Promise<ReceiptResponse> => {
      if (!token) {
        throw new Error("Missing receipt token");
      }

      const { data } = await api.get<ReceiptResponse>(`/receipts/${encodeURIComponent(token)}`);
      return data;
    },
    retry: false,
  });

  if (!token) {
    return (
      <div className="min-h-screen bg-white px-4 py-10 text-slate-900">
        <div className="mx-auto flex min-h-[70vh] max-w-sm items-center justify-center text-center">
          <div>
            <h1 className="text-2xl font-semibold">Receipt not found</h1>
          </div>
        </div>
      </div>
    );
  }

  if (receiptQuery.isLoading) {
    return (
      <div className="min-h-screen bg-white px-4 py-10 text-slate-900">
        <div className="mx-auto flex min-h-[70vh] max-w-sm items-center justify-center text-center">
          <div>
            <div className="text-sm uppercase tracking-[0.3em] text-slate-400">Loading receipt</div>
            <div className="mt-3 text-lg font-medium">Please wait...</div>
          </div>
        </div>
      </div>
    );
  }

  if (receiptQuery.isError) {
    const notFound = isAxiosError(receiptQuery.error) && receiptQuery.error.response?.status === 404;

    return (
      <div className="min-h-screen bg-white px-4 py-10 text-slate-900">
        <div className="mx-auto flex min-h-[70vh] max-w-sm items-center justify-center text-center">
          <div>
            <h1 className="text-2xl font-semibold">{notFound ? "Receipt not found" : "Unable to load receipt"}</h1>
            {!notFound && (
              <p className="mt-3 text-sm text-slate-500">Please try again in a moment.</p>
            )}
          </div>
        </div>
      </div>
    );
  }

  const receipt = receiptQuery.data;

  if (!receipt) {
    return null;
  }

  const hasDiscount = receipt.discount_total > 0;

  return (
    <div className="min-h-screen bg-white px-4 py-8 text-slate-900">
      <main className="mx-auto w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-5 shadow-sm print:rounded-none print:border-0 print:shadow-none">
        <header className="border-b border-dashed border-slate-300 pb-4 text-center">
          <h1 className="text-2xl font-bold tracking-tight text-slate-950">{receipt.store_name}</h1>
          <p className="mt-2 text-sm text-slate-500">{formatDateTime(receipt.created_at)}</p>
          <div className="mt-2 text-xs uppercase tracking-[0.3em] text-slate-400">Receipt</div>
        </header>

        <section className="border-b border-dashed border-slate-300 py-4">
          <div className="space-y-3">
            {receipt.items.map((item, index) => (
              <div key={`${item.item_number ?? item.name}-${index}`} className="space-y-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-950">{item.name}</div>
                    <div className="text-xs text-slate-500">{item.item_number || "No item number"}</div>
                  </div>
                  <div className="shrink-0 text-right text-sm font-medium text-slate-900">
                    {formatMoney(item.line_total)}
                  </div>
                </div>
                <div className="text-xs text-slate-500">
                  {item.qty} x {formatMoney(item.unit_price)}
                  <span className="mx-1">=</span>
                  {formatMoney(item.line_total)}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-2 py-4 text-sm">
          <Row label="Subtotal" value={formatMoney(receipt.subtotal)} />
          {hasDiscount && <Row label="Discount" value={`-${formatMoney(receipt.discount_total)}`} tone="text-emerald-700" />}
          <Row label="Total" value={formatMoney(receipt.total)} bold />
          <Row label="Payment" value={formatPaymentMethod(receipt)} />
        </section>

        <footer className="border-t border-dashed border-slate-300 pt-4 text-center">
          <p className="text-sm font-medium text-slate-700">Thank you for your purchase!</p>
          <p className="mt-2 text-xs text-slate-400">Receipt token: {receipt.receipt_token}</p>
        </footer>
      </main>
    </div>
  );
}

function Row({
  label,
  value,
  bold = false,
  tone = "text-slate-900",
}: {
  label: string;
  value: string;
  bold?: boolean;
  tone?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className={`text-slate-500 ${bold ? "font-semibold text-slate-700" : ""}`}>{label}</span>
      <span className={`text-right ${tone} ${bold ? "text-base font-bold" : ""}`}>{value}</span>
    </div>
  );
}
