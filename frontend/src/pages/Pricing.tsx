import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeDollarSign, Loader2, PencilLine, Plus, Save, X } from "lucide-react";

import { api } from "../api/client";
import ProductImage from "../components/ProductImage";

type CostingRow = {
  product_id: string;
  item_number: string | null;
  image_url: string | null;
  name: string;
  packing: string | null;
  boxes_per_case: number | null;
  units_per_box: number | null;
  case_cost: number | null;
  markup_multiplier: number | null;
  retail_price: number | null;
  category_name: string | null;
};

type CostingFormState = {
  product_id: string;
  boxes_per_case: string;
  units_per_box: string;
  case_cost: string;
  markup_multiplier: string;
  packing: string | null;
  name: string;
};

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `$${value.toFixed(2)}`;
}

function formatPacking(packing: string | null, boxes?: number | null, units?: number | null) {
  if (boxes !== undefined && boxes !== null && units !== undefined && units !== null) {
    return `${boxes} / ${units}`;
  }
  if (!packing) {
    return "—";
  }
  return packing.replace("/", " / ");
}

function parsePacking(packing: string | null) {
  if (!packing) {
    return { boxes: "", units: "" };
  }
  const [boxes, units] = packing.split("/");
  return {
    boxes: boxes?.trim() ?? "",
    units: units?.trim() ?? "",
  };
}

function computeRetailPreview(caseCost: string, boxesPerCase: string, unitsPerBox: string, markupMultiplier: string) {
  const cost = Number(caseCost);
  const boxes = Number(boxesPerCase);
  const units = Number(unitsPerBox);
  const markup = Number(markupMultiplier);
  if (![cost, boxes, units, markup].every(Number.isFinite) || boxes <= 0 || units <= 0) {
    return null;
  }
  const unitCost = cost / (boxes * units);
  return Math.round(unitCost * markup) - 0.05;
}

export default function Pricing() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<CostingFormState | null>(null);

  const costingQuery = useQuery({
    queryKey: ["costing"],
    queryFn: async (): Promise<CostingRow[]> => {
      const { data } = await api.get<CostingRow[]>("/v1/costing/");
      return data;
    },
  });

  useEffect(() => {
    if (!editing) {
      return;
    }
    const stillVisible = costingQuery.data?.some((row) => row.product_id === editing.product_id);
    if (!stillVisible) {
      setEditing(null);
    }
  }, [costingQuery.data, editing]);

  const previewRetail = useMemo(() => {
    if (!editing) {
      return null;
    }
    return computeRetailPreview(editing.case_cost, editing.boxes_per_case, editing.units_per_box, editing.markup_multiplier);
  }, [editing]);

  const upsertMutation = useMutation({
    mutationFn: async (payload: {
      product_id: string;
      boxes_per_case: number;
      units_per_box: number;
      case_cost: number;
      markup_multiplier: number;
    }) => {
      const { data } = await api.post<CostingRow>("/v1/costing/", payload);
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["costing"] });
      setEditing(null);
    },
  });

  function beginEdit(row: CostingRow) {
    const packing = parsePacking(row.packing);
    setEditing({
      product_id: row.product_id,
      boxes_per_case: row.boxes_per_case?.toString() ?? packing.boxes,
      units_per_box: row.units_per_box?.toString() ?? packing.units,
      case_cost: row.case_cost?.toString() ?? "",
      markup_multiplier: row.markup_multiplier?.toString() ?? "",
      packing: row.packing,
      name: row.name,
    });
  }

  function updateField(field: keyof Omit<CostingFormState, "product_id" | "packing" | "name">, value: string) {
    setEditing((current) => (current ? { ...current, [field]: value } : current));
  }

  function saveEditing() {
    if (!editing) {
      return;
    }
    const boxes = Number(editing.boxes_per_case);
    const units = Number(editing.units_per_box);
    const caseCost = Number(editing.case_cost);
    const markup = Number(editing.markup_multiplier);
    if (![boxes, units, caseCost, markup].every(Number.isFinite) || boxes <= 0 || units <= 0) {
      return;
    }
    upsertMutation.mutate({
      product_id: editing.product_id,
      boxes_per_case: boxes,
      units_per_box: units,
      case_cost: caseCost,
      markup_multiplier: markup,
    });
  }

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-6 backdrop-blur sm:px-6">
        <div className="mx-auto flex max-w-7xl flex-col gap-3">
          <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Pricing</div>
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight text-gray-50">Costing and retail pricing</h1>
              <p className="mt-2 max-w-3xl text-sm text-gray-400">
                Maintain case cost, markup, and the derived retail price for in-store products.
              </p>
            </div>
            <div className="rounded-3xl border border-gray-800 bg-gray-900 px-4 py-3">
              <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Visible products</div>
              <div className="mt-1 text-2xl font-semibold text-gray-50">
                {costingQuery.data?.length?.toLocaleString() ?? "0"}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <div className="space-y-4 lg:hidden">
          {costingQuery.isLoading ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">
              Loading pricing...
            </div>
          ) : costingQuery.isError ? (
            <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-red-200">
              Unable to load pricing.
            </div>
          ) : (costingQuery.data ?? []).length === 0 ? (
            <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-8 text-center text-sm text-gray-500">
              No in-store products found.
            </div>
          ) : (
            costingQuery.data?.map((row) => {
              const hasCosting = row.boxes_per_case !== null && row.units_per_box !== null && row.case_cost !== null;
              return (
                <div key={row.product_id} className="rounded-3xl border border-gray-800 bg-gray-900 p-4">
                  <div className="flex items-start gap-3">
                    <ProductImage imageUrl={row.image_url} name={row.name} size="xs" />
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-gray-50">{row.name}</div>
                      <div className="mt-1 text-xs text-gray-500">
                        {row.item_number || "No item number"}
                        {row.category_name ? ` Â· ${row.category_name}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => beginEdit(row)}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-medium text-gray-100 transition hover:border-orange-500 hover:text-orange-200"
                    >
                      {hasCosting ? <PencilLine className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                      {hasCosting ? "Edit" : "Add"}
                    </button>
                  </div>

                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Packing</div>
                      <div className="mt-1 text-gray-300">
                        {formatPacking(row.packing, row.boxes_per_case, row.units_per_box)}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Retail</div>
                      <div className="mt-1 text-gray-300">{formatMoney(row.retail_price)}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Case cost</div>
                      <div className="mt-1 text-gray-300">{formatMoney(row.case_cost)}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Markup</div>
                      <div className="mt-1 text-gray-300">
                        {row.markup_multiplier === null ? "—" : row.markup_multiplier.toFixed(4)}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="hidden overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 lg:block">
          <table className="min-w-full divide-y divide-gray-800">
            <thead className="bg-gray-950">
              <tr className="text-left text-xs uppercase tracking-[0.2em] text-gray-500">
                <th className="px-4 py-3">Product name</th>
                <th className="px-4 py-3">Packing</th>
                <th className="px-4 py-3 text-right">Case Cost</th>
                <th className="px-4 py-3 text-right">Markup</th>
                <th className="px-4 py-3 text-right">Retail Price</th>
                <th className="px-4 py-3 text-right">Edit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800">
              {costingQuery.isLoading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-400">
                    Loading pricing...
                  </td>
                </tr>
              ) : costingQuery.isError ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-red-200">
                    Unable to load pricing.
                  </td>
                </tr>
              ) : (costingQuery.data ?? []).length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">
                    No in-store products found.
                  </td>
                </tr>
              ) : (
                costingQuery.data?.map((row) => {
                  const hasCosting = row.boxes_per_case !== null && row.units_per_box !== null && row.case_cost !== null;
                  return (
                    <tr key={row.product_id} className="bg-transparent hover:bg-gray-800/40">
                      <td className="px-4 py-4 align-middle">
                        <div className="flex items-center gap-3">
                          <ProductImage imageUrl={row.image_url} name={row.name} size="xs" />
                          <div>
                            <div className="font-medium text-gray-50">{row.name}</div>
                            <div className="mt-1 text-xs text-gray-500">
                              {row.item_number || "No item number"}
                              {row.category_name ? ` · ${row.category_name}` : ""}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-4 align-middle text-sm text-gray-300">
                        {formatPacking(row.packing, row.boxes_per_case, row.units_per_box)}
                      </td>
                      <td className="px-4 py-4 align-middle text-right text-sm text-gray-200">
                        {formatMoney(row.case_cost)}
                      </td>
                      <td className="px-4 py-4 align-middle text-right text-sm text-gray-200">
                        {row.markup_multiplier === null ? "—" : row.markup_multiplier.toFixed(4)}
                      </td>
                      <td className="px-4 py-4 align-middle text-right">
                        {hasCosting ? (
                          <span className="inline-flex items-center gap-2 rounded-full border border-orange-500/30 bg-orange-500/10 px-3 py-1 text-sm font-semibold text-orange-200">
                            <BadgeDollarSign className="h-4 w-4" />
                            {formatMoney(row.retail_price)}
                          </span>
                        ) : (
                          <span className="inline-flex items-center rounded-full border border-gray-700 bg-gray-800 px-3 py-1 text-xs uppercase tracking-[0.2em] text-gray-400">
                            No pricing
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-4 align-middle text-right">
                        <button
                          type="button"
                          onClick={() => beginEdit(row)}
                          className="inline-flex items-center gap-2 rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-medium text-gray-100 transition hover:border-orange-500 hover:text-orange-200"
                        >
                          {hasCosting ? <PencilLine className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
                          {hasCosting ? "Edit" : "Add"}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4 sm:py-8">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl sm:max-h-[90vh] sm:max-w-[42rem]">
            <div className="flex items-start justify-between gap-4 border-b border-gray-800 px-4 py-5 sm:px-6">
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Edit pricing</div>
                <h2 className="mt-2 text-2xl font-semibold text-gray-50">{editing.name}</h2>
                <div className="mt-1 text-sm text-gray-400">{editing.packing || "No packing on file"}</div>
              </div>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="rounded-2xl border border-gray-800 bg-gray-950 p-2 text-gray-400 transition hover:border-gray-700 hover:text-gray-100"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="max-h-[calc(100vh-14rem)] overflow-auto px-4 py-6 sm:max-h-none sm:px-6 md:grid md:grid-cols-2 md:gap-4">
              <Field
                label="Boxes per case"
                value={editing.boxes_per_case}
                onChange={(value) => updateField("boxes_per_case", value)}
                type="number"
                min="1"
              />
              <Field
                label="Units per box"
                value={editing.units_per_box}
                onChange={(value) => updateField("units_per_box", value)}
                type="number"
                min="1"
              />
              <Field
                label="Case cost"
                value={editing.case_cost}
                onChange={(value) => updateField("case_cost", value)}
                type="number"
                min="0"
                step="0.01"
              />
              <Field
                label="Markup multiplier"
                value={editing.markup_multiplier}
                onChange={(value) => updateField("markup_multiplier", value)}
                type="number"
                min="0"
                step="0.0001"
              />
            </div>

            <div className="border-t border-gray-800 px-4 py-4 sm:px-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Retail preview</div>
                  <div className="mt-2 text-3xl font-semibold text-orange-200">
                    {previewRetail === null ? "—" : formatMoney(previewRetail)}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setEditing(null)}
                    className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm font-medium text-gray-200 transition hover:border-gray-700"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={saveEditing}
                    disabled={upsertMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                  >
                    {upsertMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    Save pricing
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type,
  min,
  step,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type: "number" | "text";
  min?: string;
  step?: string;
}) {
  return (
    <label className="space-y-2 text-sm text-gray-300">
      <span className="text-xs uppercase tracking-[0.25em] text-gray-500">{label}</span>
      <input
        type={type}
        value={value}
        min={min}
        step={step}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-orange-500"
      />
    </label>
  );
}
