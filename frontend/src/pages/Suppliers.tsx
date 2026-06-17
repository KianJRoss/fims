import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Building2, Link2, Loader2, Plus, Search, Trash2, Unlink, X,
} from "lucide-react";

import { api } from "../api/client";

// ─── Types ──────────────────────────────────────────────────────────────────

type Supplier = {
  id: number;
  name: string;
  code: string | null;
  contact_info: Record<string, unknown> | null;
  notes: string | null;
  product_count: number;
  unmatched_count: number;
};

type SupplierProduct = {
  id: number;
  supplier_id: number;
  product_id: string | null;
  supplier_item_number: string | null;
  supplier_product_name: string | null;
  supplier_barcode: string | null;
  supplier_cost: number | null;
  last_seen: string;
  raw_data: Record<string, unknown> | null;
  product_name: string | null;
  product_item_number: string | null;
};

type SupplierDetail = Supplier & {
  products: { items: SupplierProduct[]; total: number; skip: number; limit: number };
};

type ProductSearchResult = {
  id: string;
  name: string;
  item_number: string | null;
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatDate(v: string | null | undefined) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString();
}

function formatMoney(v: number | null) {
  if (v === null || v === undefined) return "—";
  return `$${v.toFixed(2)}`;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function Suppliers() {
  const queryClient = useQueryClient();

  const [selectedSupplierId, setSelectedSupplierId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [unmatchedOnly, setUnmatchedOnly] = useState(false);

  // Create form state
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newNotes, setNewNotes] = useState("");

  // Matching UI state
  const [matchingRowId, setMatchingRowId] = useState<number | null>(null);
  const [matchSearch, setMatchSearch] = useState("");
  const [debouncedMatchSearch, setDebouncedMatchSearch] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedMatchSearch(matchSearch), 300);
    return () => clearTimeout(t);
  }, [matchSearch]);

  // ── Queries ─────────────────────────────────────────────────────────────────

  const suppliersQuery = useQuery({
    queryKey: ["suppliers"],
    queryFn: async (): Promise<Supplier[]> => (await api.get("/v1/suppliers/")).data,
  });

  const supplierDetailQuery = useQuery({
    queryKey: ["supplier", selectedSupplierId, unmatchedOnly],
    queryFn: async (): Promise<SupplierDetail> =>
      (
        await api.get(`/v1/suppliers/${selectedSupplierId}`, {
          params: { unmatched_only: unmatchedOnly, limit: 100 },
        })
      ).data,
    enabled: selectedSupplierId !== null,
  });

  const productSearchQuery = useQuery({
    queryKey: ["product-search", debouncedMatchSearch],
    queryFn: async (): Promise<ProductSearchResult[]> =>
      (await api.get(`/v1/products/?q=${encodeURIComponent(debouncedMatchSearch)}&limit=20`)).data,
    enabled: matchingRowId !== null && debouncedMatchSearch.trim().length > 0,
  });

  // ── Mutations ────────────────────────────────────────────────────────────────

  const createSupplierMutation = useMutation({
    mutationFn: async () =>
      (
        await api.post("/v1/suppliers/", {
          name: newName,
          code: newCode || null,
          notes: newNotes || null,
        })
      ).data as Supplier,
    onSuccess: async (supplier) => {
      closeCreateModal();
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
      setSelectedSupplierId(supplier.id);
    },
  });

  const deleteSupplierMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/v1/suppliers/${id}`);
      return id;
    },
    onSuccess: async (id) => {
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
      if (selectedSupplierId === id) setSelectedSupplierId(null);
    },
  });

  const matchMutation = useMutation({
    mutationFn: async ({ row, productId }: { row: SupplierProduct; productId: string | null }) =>
      (
        await api.patch(`/v1/suppliers/${row.supplier_id}/products/${row.id}`, {
          product_id: productId,
        })
      ).data as SupplierProduct,
    onSuccess: async () => {
      setMatchingRowId(null);
      setMatchSearch("");
      await queryClient.invalidateQueries({ queryKey: ["supplier", selectedSupplierId, unmatchedOnly] });
      await queryClient.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });

  // ── Derived state ─────────────────────────────────────────────────────────────

  const suppliers = suppliersQuery.data ?? [];
  const detail = supplierDetailQuery.data ?? null;
  const products = detail?.products.items ?? [];

  function closeCreateModal() {
    setCreateOpen(false);
    setNewName("");
    setNewCode("");
    setNewNotes("");
  }

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      {/* Header */}
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Suppliers</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">Supplier Management</h1>
          </div>
          <button
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 transition"
          >
            <Plus className="h-4 w-4" /> New Supplier
          </button>
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-81px)] grid-cols-1 lg:grid-cols-[320px_1fr]">
        {/* Sidebar: supplier list */}
        <aside className="border-b border-gray-800 bg-gray-900/90 px-4 py-5 lg:border-b-0 lg:border-r">
          <div className="mb-3 text-[11px] uppercase tracking-[0.25em] text-gray-600">All Suppliers</div>
          {suppliersQuery.isLoading && <div className="p-3 text-sm text-gray-500">Loading...</div>}
          {suppliers.length === 0 && !suppliersQuery.isLoading && (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-950 p-6 text-center text-sm text-gray-500">
              No suppliers yet. Create one to get started.
            </div>
          )}
          <div className="space-y-2">
            {suppliers.map((supplier) => (
              <button
                key={supplier.id}
                onClick={() => setSelectedSupplierId(supplier.id)}
                className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                  selectedSupplierId === supplier.id
                    ? "border-orange-500 bg-orange-500/10"
                    : "border-gray-800 bg-gray-950 hover:border-gray-700"
                }`}
              >
                <div className="flex items-center gap-2">
                  <Building2 className="h-4 w-4 shrink-0 text-orange-300" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-gray-50">{supplier.name}</div>
                    <div className="text-xs text-gray-500">{supplier.code || "No code"}</div>
                  </div>
                </div>
                <div className="mt-2 flex items-center gap-2 text-xs">
                  <span className="rounded-full border border-gray-700 bg-gray-900 px-2 py-0.5 text-gray-300">
                    {supplier.product_count} products
                  </span>
                  {supplier.unmatched_count > 0 && (
                    <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-amber-300">
                      {supplier.unmatched_count} unmatched
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        </aside>

        {/* Main panel: supplier detail */}
        <main className="overflow-auto px-4 py-6 sm:px-6">
          {!selectedSupplierId ? (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-10 text-center">
              <Building2 className="mx-auto h-10 w-10 text-gray-600 mb-3" />
              <div className="text-sm text-gray-400">Select a supplier from the left to view its catalog.</div>
            </div>
          ) : supplierDetailQuery.isLoading || !detail ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
              Loading supplier...
            </div>
          ) : (
            <div className="space-y-6">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h2 className="text-2xl font-semibold text-gray-50">{detail.name}</h2>
                  <div className="mt-1 text-sm text-gray-400">{detail.code || "No code"}</div>
                  {detail.notes && <div className="mt-2 max-w-xl text-sm text-gray-500">{detail.notes}</div>}
                </div>
                <button
                  onClick={() => {
                    if (window.confirm(`Delete supplier "${detail.name}"?`)) {
                      deleteSupplierMutation.mutate(detail.id);
                    }
                  }}
                  className="inline-flex items-center gap-2 rounded-2xl border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-200 hover:bg-red-500/10"
                >
                  <Trash2 className="h-3.5 w-3.5" /> Delete Supplier
                </button>
              </div>

              {deleteSupplierMutation.isError && (
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
                  Could not delete supplier — it likely still has linked supplier products.
                </div>
              )}

              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-gray-100">
                  Supplier Catalog ({detail.products.total})
                </div>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={unmatchedOnly}
                    onChange={(e) => setUnmatchedOnly(e.target.checked)}
                    className="h-4 w-4 rounded border-gray-700 bg-gray-950 text-orange-500 focus:ring-orange-500"
                  />
                  Unmatched only
                </label>
              </div>

              <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-900">
                <table className="min-w-full divide-y divide-gray-800">
                  <thead className="bg-gray-950">
                    <tr className="text-left text-[11px] uppercase tracking-[0.2em] text-gray-500">
                      <th className="px-4 py-3">Supplier Item</th>
                      <th className="px-4 py-3">Supplier Name</th>
                      <th className="px-4 py-3">Barcode</th>
                      <th className="px-4 py-3">Cost</th>
                      <th className="px-4 py-3">Last Seen</th>
                      <th className="px-4 py-3">Matched Product</th>
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800">
                    {products.map((row) => (
                      <tr key={row.id} className="hover:bg-gray-800/30">
                        <td className="px-4 py-3 text-sm text-gray-300">{row.supplier_item_number || "—"}</td>
                        <td className="px-4 py-3 text-sm text-gray-300">{row.supplier_product_name || "—"}</td>
                        <td className="px-4 py-3 text-sm text-gray-300">{row.supplier_barcode || "—"}</td>
                        <td className="px-4 py-3 text-sm text-gray-300">{formatMoney(row.supplier_cost)}</td>
                        <td className="px-4 py-3 text-sm text-gray-300">{formatDate(row.last_seen)}</td>
                        <td className="px-4 py-3 text-sm">
                          {row.product_id ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300">
                              {row.product_name || row.product_id}
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300">
                              Unmatched
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => {
                                setMatchingRowId(row.id);
                                setMatchSearch(row.supplier_product_name || "");
                              }}
                              className="inline-flex items-center gap-1 rounded-xl border border-gray-800 bg-gray-950 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-900"
                            >
                              <Link2 className="h-3.5 w-3.5" /> Match
                            </button>
                            {row.product_id && (
                              <button
                                onClick={() => matchMutation.mutate({ row, productId: null })}
                                disabled={matchMutation.isPending}
                                className="inline-flex items-center gap-1 rounded-xl border border-gray-800 bg-gray-950 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-900 disabled:opacity-50"
                              >
                                <Unlink className="h-3.5 w-3.5" /> Unmatch
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                    {products.length === 0 && (
                      <tr>
                        <td colSpan={7} className="px-4 py-12 text-center text-sm text-gray-500">
                          {unmatchedOnly ? "No unmatched products." : "No supplier products yet."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Create supplier modal */}
      {createOpen && (
        <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl sm:max-h-[90vh] sm:max-w-[32rem]">
            <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
              <div className="text-lg font-semibold text-gray-50">New Supplier</div>
              <button
                onClick={closeCreateModal}
                className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-400 hover:text-gray-100"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-5">
              <label className="block">
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Name</div>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Jake's Fireworks"
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                />
              </label>
              <label className="block">
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Code</div>
                <input
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  placeholder="JAKES"
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                />
              </label>
              <label className="block">
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Notes</div>
                <textarea
                  rows={3}
                  value={newNotes}
                  onChange={(e) => setNewNotes(e.target.value)}
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500 resize-y"
                />
              </label>
              <div className="flex justify-end gap-3">
                <button
                  onClick={closeCreateModal}
                  className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-2.5 text-sm text-gray-300 hover:border-gray-700"
                >
                  Cancel
                </button>
                <button
                  onClick={() => createSupplierMutation.mutate()}
                  disabled={!newName.trim() || createSupplierMutation.isPending}
                  className="rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 disabled:bg-gray-700 transition"
                >
                  {createSupplierMutation.isPending ? "Creating…" : "Create Supplier"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Match product modal */}
      {matchingRowId !== null && (
        <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl sm:max-h-[80vh] sm:max-w-[36rem]">
            <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
              <div className="text-lg font-semibold text-gray-50">Match to Internal Product</div>
              <button
                onClick={() => {
                  setMatchingRowId(null);
                  setMatchSearch("");
                }}
                className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-400 hover:text-gray-100"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-4 p-5">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input
                  autoFocus
                  value={matchSearch}
                  onChange={(e) => setMatchSearch(e.target.value)}
                  placeholder="Search products by name or item number..."
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-9 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                />
              </div>
              <div className="max-h-80 space-y-2 overflow-auto">
                {productSearchQuery.isLoading && (
                  <div className="flex items-center justify-center gap-2 p-6 text-sm text-gray-500">
                    <Loader2 className="h-4 w-4 animate-spin" /> Searching...
                  </div>
                )}
                {(productSearchQuery.data ?? []).map((product) => (
                  <button
                    key={product.id}
                    onClick={() => {
                      const row = products.find((p) => p.id === matchingRowId);
                      if (row) matchMutation.mutate({ row, productId: product.id });
                    }}
                    disabled={matchMutation.isPending}
                    className="flex w-full items-center justify-between rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-left text-sm text-gray-100 hover:border-orange-500 hover:bg-orange-500/10 disabled:opacity-50"
                  >
                    <span>{product.name}</span>
                    <span className="text-xs text-gray-500">{product.item_number}</span>
                  </button>
                ))}
                {!productSearchQuery.isLoading &&
                  matchSearch.trim().length > 0 &&
                  (productSearchQuery.data ?? []).length === 0 && (
                    <div className="p-6 text-center text-sm text-gray-500">No matching products found.</div>
                  )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
