import { useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Banknote, CalendarDays, ChevronDown, ChevronUp, CreditCard, PackageSearch, ReceiptText } from "lucide-react";

import { api } from "../api/client";

type SaleSummary = {
  id: string;
  receipt_token: string;
  created_at: string;
  payment_method: string;
  total: number;
  item_count: number;
};

type DailyReport = {
  date: string;
  transaction_count: number;
  revenue: number;
  discount_total: number;
  avg_sale: number;
  cash_count: number;
  card_count: number;
  cash_revenue: number;
  card_revenue: number;
  transactions: SaleSummary[];
};

type SaleDetail = {
  id: string;
  receipt_token: string;
  created_at: string;
  completed_at: string;
  payment_method: string;
  card_last4: string | null;
  subtotal: number;
  discount_total: number;
  total: number;
  items: Array<{
    id: string;
    product_id: string;
    product_name: string | null;
    item_number: string | null;
    qty: number;
    unit_price: number;
    override_price: number | null;
    discount_amount: number;
    line_total: number;
  }>;
};

function formatMoney(value: number) {
  return `$${value.toFixed(2)}`;
}

function formatDateInput(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-US", { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function paymentClass(method: string) {
  if (method === "CARD") {
    return "border-orange-500/30 bg-orange-500/10 text-orange-200";
  }
  return "border-gray-700 bg-gray-800 text-gray-200";
}

export default function Receipts() {
  const [selectedDate, setSelectedDate] = useState(() => formatDateInput(new Date()));
  const [expandedSaleId, setExpandedSaleId] = useState<string | null>(null);

  const reportQuery = useQuery({
    queryKey: ["receipts", selectedDate],
    queryFn: async (): Promise<DailyReport> => {
      const { data } = await api.get(`/v1/reports/daily?date=${encodeURIComponent(selectedDate)}`);
      return data;
    },
  });

  return (
    <div className="min-h-full bg-gray-950 px-4 py-6 text-gray-100 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <div className="rounded-3xl border border-gray-800 bg-gray-900 px-6 py-6">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-end">
            <label className="flex flex-col gap-2 text-sm text-gray-400">
              <span className="flex items-center gap-2 text-xs uppercase tracking-[0.25em] text-gray-500">
                <CalendarDays className="h-4 w-4 text-orange-300/80" />
                Date
              </span>
              <input
                type="date"
                value={selectedDate}
                onChange={(event) => {
                  setSelectedDate(event.target.value);
                  setExpandedSaleId(null);
                }}
                className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none transition focus:border-orange-500"
              />
            </label>
          </div>
        </div>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Sales"
            value={reportQuery.isLoading ? "-" : String(reportQuery.data?.transaction_count ?? 0)}
            icon={<ReceiptText className="h-4 w-4" />}
          />
          <StatCard
            label="Revenue"
            value={reportQuery.isLoading ? "-" : formatMoney(reportQuery.data?.revenue ?? 0)}
            icon={<Banknote className="h-4 w-4" />}
            accent="text-orange-200"
          />
          <StatCard
            label="Cash"
            value={reportQuery.isLoading ? "-" : String(reportQuery.data?.cash_count ?? 0)}
            subvalue={reportQuery.isLoading ? "-" : formatMoney(reportQuery.data?.cash_revenue ?? 0)}
            icon={<Banknote className="h-4 w-4" />}
          />
          <StatCard
            label="Card"
            value={reportQuery.isLoading ? "-" : String(reportQuery.data?.card_count ?? 0)}
            subvalue={reportQuery.isLoading ? "-" : formatMoney(reportQuery.data?.card_revenue ?? 0)}
            icon={<CreditCard className="h-4 w-4" />}
            accent="text-orange-200"
          />
        </section>

        <section className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
          <div className="flex items-center justify-between gap-4 border-b border-gray-800 px-6 py-4">
            <div>
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Transactions</div>
              <div className="mt-1 text-sm text-gray-400">{selectedDate}</div>
            </div>
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">
              {reportQuery.isLoading ? "Loading" : `${reportQuery.data?.transactions.length ?? 0} rows`}
            </div>
          </div>

          {reportQuery.isError ? (
            <div className="px-6 py-10 text-sm text-red-200">Unable to load receipts.</div>
          ) : reportQuery.isLoading ? (
            <div className="px-6 py-10 text-sm text-gray-400">Loading receipts...</div>
          ) : reportQuery.data?.transactions.length ? (
            <div className="divide-y divide-gray-800">
              {reportQuery.data.transactions.map((sale) => (
                <ReceiptRow
                  key={sale.id}
                  sale={sale}
                  expanded={expandedSaleId === sale.id}
                  onToggle={() => setExpandedSaleId((current) => (current === sale.id ? null : sale.id))}
                />
              ))}
            </div>
          ) : (
            <div className="px-6 py-10 text-sm text-gray-400">No sales found for this date.</div>
          )}
        </section>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  subvalue,
  icon,
  accent = "text-gray-50",
}: {
  label: string;
  value: string;
  subvalue?: string;
  icon: ReactNode;
  accent?: string;
}) {
  return (
    <div className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-[0.25em] text-gray-500">{label}</div>
          <div className={`text-2xl font-semibold ${accent}`}>{value}</div>
          {subvalue ? <div className="text-sm text-gray-400">{subvalue}</div> : null}
        </div>
        <div className="rounded-2xl border border-gray-800 bg-gray-950 p-3 text-orange-300">{icon}</div>
      </div>
    </div>
  );
}

function ReceiptRow({
  sale,
  expanded,
  onToggle,
}: {
  sale: SaleSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["receipts", "transaction", sale.id],
    queryFn: async (): Promise<SaleDetail> => {
      const { data } = await api.get(`/v1/reports/transaction/${sale.id}`);
      return data;
    },
    enabled: expanded,
  });

  return (
    <div className="bg-gray-900">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-4 px-6 py-4 text-left transition hover:bg-gray-800/50"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <span className="text-sm font-medium text-gray-100">{formatTime(sale.created_at)}</span>
            <span
              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] ${paymentClass(
                sale.payment_method
              )}`}
            >
              {sale.payment_method}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-500">
            <span className="font-mono">{sale.receipt_token}</span>
            <span>{sale.item_count} items</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-sm font-semibold text-gray-50">{formatMoney(sale.total)}</div>
            <div className="text-xs text-gray-500">{sale.item_count} line items</div>
          </div>
          {expanded ? <ChevronUp className="h-5 w-5 text-gray-400" /> : <ChevronDown className="h-5 w-5 text-gray-400" />}
        </div>
      </button>

      {expanded ? (
        <div className="border-t border-gray-800 bg-gray-950 px-6 py-5">
          {detailQuery.isLoading ? (
            <div className="text-sm text-gray-400">Loading transaction details...</div>
          ) : detailQuery.isError ? (
            <div className="text-sm text-red-200">Unable to load transaction details.</div>
          ) : detailQuery.data ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-sm text-gray-300">
                <PackageSearch className="h-4 w-4 text-orange-300" />
                <span className="font-mono">{detailQuery.data.receipt_token}</span>
              </div>

              <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
                <div className="border-b border-gray-800 px-4 py-3 text-xs uppercase tracking-[0.25em] text-gray-500">
                  Line items
                </div>
                <div className="divide-y divide-gray-800">
                  {detailQuery.data.items.map((item) => (
                    <div
                      key={item.id}
                      className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1.5fr)_auto_auto] md:items-center"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-gray-50">{item.product_name ?? "Unknown item"}</div>
                        <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-500">
                          <span className="font-mono">{item.item_number ?? item.product_id}</span>
                          <span>
                            {item.qty} x {formatMoney(item.unit_price)}
                          </span>
                        </div>
                      </div>
                      <div className="text-sm text-gray-300">
                        {item.discount_amount > 0 ? `-${formatMoney(item.discount_amount)}` : formatMoney(0)}
                      </div>
                      <div className="text-right text-sm font-semibold text-gray-50">
                        {formatMoney(item.line_total)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
