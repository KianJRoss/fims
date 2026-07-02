import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Banknote,
  ChevronDown,
  ChevronUp,
  CreditCard,
  Receipt,
  TrendingUp,
  CalendarDays,
} from "lucide-react";

import { api } from "../api/client";

type TransactionSummary = {
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
  top_products?: Array<{
    product_id: string;
    name: string | null;
    item_number: string | null;
    qty: number;
    revenue: number;
  }>;
  transactions: TransactionSummary[];
};

type TransactionDetail = {
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
    product_name: string;
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

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function paymentBadgeClass(method: string) {
  if (method === "CARD") {
    return "border-orange-500/30 bg-orange-500/10 text-orange-200";
  }
  if (method === "CASH") {
    return "border-gray-700 bg-gray-800 text-gray-200";
  }
  return "border-gray-700 bg-gray-800 text-gray-200";
}

export default function Reports() {
  const [selectedDate, setSelectedDate] = useState(() => formatDateInput(new Date()));
  const [expandedTransactionId, setExpandedTransactionId] = useState<string | null>(null);

  const dailyReportQuery = useQuery({
    queryKey: ["reports", "daily", selectedDate],
    queryFn: async (): Promise<DailyReport> => {
      const { data } = await api.get(`/v1/reports/daily?date=${encodeURIComponent(selectedDate)}`);
      return data;
    },
  });

  const report = dailyReportQuery.data;
  const topProducts = report?.top_products ?? [];

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
                  setExpandedTransactionId(null);
                }}
                className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none transition focus:border-orange-500"
              />
            </label>
          </div>
        </div>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <SummaryCard
            label="Transactions"
            icon={<Receipt className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : String(report?.transaction_count ?? 0)}
            accent="text-orange-200"
          />
          <SummaryCard
            label="Revenue"
            icon={<TrendingUp className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : formatMoney(report?.revenue ?? 0)}
            accent="text-orange-200"
          />
          <SummaryCard
            label="Discounts"
            icon={<TrendingUp className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : formatMoney(report?.discount_total ?? 0)}
            accent="text-red-200"
          />
          <SummaryCard
            label="Avg Sale"
            icon={<TrendingUp className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : formatMoney(report?.avg_sale ?? 0)}
            accent="text-gray-50"
          />
          <SummaryCard
            label="Cash"
            icon={<Banknote className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : String(report?.cash_count ?? 0)}
            subvalue={dailyReportQuery.isLoading ? "-" : formatMoney(report?.cash_revenue ?? 0)}
            accent="text-gray-50"
          />
          <SummaryCard
            label="Card"
            icon={<CreditCard className="h-4 w-4" />}
            value={dailyReportQuery.isLoading ? "-" : String(report?.card_count ?? 0)}
            subvalue={dailyReportQuery.isLoading ? "-" : formatMoney(report?.card_revenue ?? 0)}
            accent="text-orange-200"
          />
        </section>

        <section className="rounded-3xl border border-gray-800 bg-gray-900">
          <div className="border-b border-gray-800 px-6 py-4">
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Top Sellers</div>
            <div className="mt-1 text-sm text-gray-400">{selectedDate}</div>
          </div>
          {dailyReportQuery.isLoading ? (
            <div className="px-6 py-8 text-sm text-gray-400">Loading top sellers...</div>
          ) : topProducts.length === 0 ? (
            <div className="px-6 py-8 text-sm text-gray-400">No sales yet.</div>
          ) : (
            <div className="divide-y divide-gray-800">
              {topProducts.slice(0, 10).map((product, index) => (
                <div
                  key={product.product_id}
                  className="grid gap-3 px-6 py-4 sm:grid-cols-[auto_minmax(0,1fr)_auto_auto] sm:items-center"
                >
                  <div className="text-sm font-semibold text-gray-500">#{index + 1}</div>
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-gray-50">
                      {product.name ?? product.item_number ?? "Unknown"}
                    </div>
                    <div className="mt-1 text-xs text-gray-500">{product.item_number ?? product.product_id}</div>
                  </div>
                  <div className="text-sm text-gray-300">{product.qty} sold</div>
                  <div className="text-sm font-semibold text-orange-200">{formatMoney(product.revenue)}</div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
          <div className="flex items-center justify-between gap-4 border-b border-gray-800 px-6 py-4">
            <div>
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Transactions</div>
              <div className="mt-1 text-sm text-gray-400">{selectedDate}</div>
            </div>
            <div className="text-xs uppercase tracking-[0.25em] text-gray-500">
              {dailyReportQuery.isLoading ? "Loading" : `${report?.transactions.length ?? 0} rows`}
            </div>
          </div>

          {dailyReportQuery.isError ? (
            <div className="px-6 py-10 text-sm text-red-200">Unable to load the daily report.</div>
          ) : dailyReportQuery.isLoading ? (
            <div className="px-6 py-10 text-sm text-gray-400">Loading report...</div>
          ) : report?.transactions.length ? (
            <div className="divide-y divide-gray-800">
              {report.transactions.map((transaction) => (
                <TransactionRow
                  key={transaction.id}
                  transaction={transaction}
                  expanded={expandedTransactionId === transaction.id}
                  onToggle={() =>
                    setExpandedTransactionId((current) => (current === transaction.id ? null : transaction.id))
                  }
                />
              ))}
            </div>
          ) : (
            <div className="px-6 py-10 text-sm text-gray-400">No transactions found for this date.</div>
          )}
        </section>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  subvalue,
  icon,
  accent,
}: {
  label: string;
  value: string;
  subvalue?: string;
  icon: ReactNode;
  accent: string;
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

function TransactionRow({
  transaction,
  expanded,
  onToggle,
}: {
  transaction: TransactionSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["reports", "transaction", transaction.id],
    queryFn: async (): Promise<TransactionDetail> => {
      const { data } = await api.get(`/v1/reports/transaction/${transaction.id}`);
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
            <span className="text-sm font-medium text-gray-100">{formatTime(transaction.created_at)}</span>
            <span
              className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] ${paymentBadgeClass(
                transaction.payment_method
              )}`}
            >
              {transaction.payment_method}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-500">
            <span className="font-mono">{transaction.receipt_token}</span>
            <span>{transaction.item_count} items</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="text-right">
            <div className="text-sm font-semibold text-gray-50">{formatMoney(transaction.total)}</div>
            <div className="text-xs text-gray-500">{transaction.item_count} line items</div>
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
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <div className="flex items-center gap-2 text-sm text-gray-300">
                    <Receipt className="h-4 w-4 text-orange-300" />
                    <span className="font-mono">{detailQuery.data.receipt_token}</span>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Completed {formatDateTime(detailQuery.data.completed_at)}
                  </div>
                </div>

                <div className="grid gap-2 text-sm text-gray-300 sm:grid-cols-2 lg:grid-cols-4">
                  <DetailPill label="Subtotal" value={formatMoney(detailQuery.data.subtotal)} />
                  <DetailPill label="Discounts" value={formatMoney(detailQuery.data.discount_total)} />
                  <DetailPill label="Total" value={formatMoney(detailQuery.data.total)} />
                  <DetailPill
                    label="Payment"
                    value={
                      detailQuery.data.payment_method === "CARD" && detailQuery.data.card_last4
                        ? `CARD **** ${detailQuery.data.card_last4}`
                        : detailQuery.data.payment_method
                    }
                  />
                </div>
              </div>

              <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
                <div className="border-b border-gray-800 px-4 py-3 text-xs uppercase tracking-[0.25em] text-gray-500">
                  Line Items
                </div>
                <div className="divide-y divide-gray-800">
                  {detailQuery.data.items.map((item) => (
                    <div
                      key={item.id}
                      className="grid gap-3 px-4 py-4 md:grid-cols-[minmax(0,1.5fr)_auto_auto] md:items-center"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-gray-50">{item.product_name}</div>
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

function DetailPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2">
      <div className="text-[11px] uppercase tracking-[0.25em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-medium text-gray-100">{value}</div>
    </div>
  );
}
