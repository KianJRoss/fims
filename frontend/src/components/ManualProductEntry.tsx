import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Search, X, Barcode as BarcodeIcon } from "lucide-react";

import { api } from "../api/client";
import ProductImage from "./ProductImage";
import VoiceInputButton from "./VoiceInputButton";

type ProductSearchResult = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
  brand_name: string | null;
};

type BarcodeRow = {
  id: number;
  barcode: string;
  barcode_type: string | null;
  is_primary: boolean;
};

type ProductDetail = {
  id: string;
  name: string;
  item_number: string | null;
  packing: string | null;
  description: string | null;
  notes: string | null;
  category_name: string | null;
  brand_name: string | null;
  shot_count: number | null;
  duration_seconds: number | null;
  effects: string | null;
  barcodes?: BarcodeRow[];
};

type FormState = {
  name: string;
  item_number: string;
  brand_name: string;
  category_name: string;
  packing: string;
  shot_count: string;
  duration_seconds: string;
  effects: string;
  description: string;
  notes: string;
  barcode: string;
  price: string;
};

const EMPTY_FORM: FormState = {
  name: "",
  item_number: "",
  brand_name: "",
  category_name: "",
  packing: "",
  shot_count: "",
  duration_seconds: "",
  effects: "",
  description: "",
  notes: "",
  barcode: "",
  price: "",
};

function detailToForm(detail: ProductDetail, barcode: string, price: string): FormState {
  return {
    name: detail.name ?? "",
    item_number: detail.item_number ?? "",
    brand_name: detail.brand_name ?? "",
    category_name: detail.category_name ?? "",
    packing: detail.packing ?? "",
    shot_count: detail.shot_count != null ? String(detail.shot_count) : "",
    duration_seconds: detail.duration_seconds != null ? String(detail.duration_seconds) : "",
    effects: detail.effects ?? "",
    description: detail.description ?? "",
    notes: detail.notes ?? "",
    barcode,
    price,
  };
}

/** Parse a price input into a non-negative number, or null if blank/invalid. */
function parsePrice(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return null;
  return n;
}

type Props = {
  prefillBarcode?: string | null;
  /** When creating a brand-new product through this component, mark it in_store
   * and flag it for the "needs more data" priority queue. Used by the Inventory
   * scanner, where "create new" always means the item is physically in the store
   * right now but was just hastily added. */
  flagAsNewInStoreItem?: boolean;
  /** When set, the component opens directly in edit mode for this product
   * (skipping the search step). Used by the Inventory scanner so a known
   * barcode immediately presents an editable info form. */
  initialEditProductId?: string | null;
  onClose?: () => void;
  onSaved?: (productId: string) => void;
};

export default function ManualProductEntry({ prefillBarcode, flagAsNewInStoreItem, initialEditProductId, onClose, onSaved }: Props) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"search" | "create" | "edit">(initialEditProductId ? "edit" : "search");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<ProductSearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [barcodes, setBarcodes] = useState<BarcodeRow[]>([]);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const searchTimerRef = useRef<number | null>(null);
  const loadedEditIdRef = useRef<string | null>(null);
  const loadedPriceRef = useRef<string>("");

  const categoryOptionsQuery = useQuery({
    queryKey: ["all-categories"],
    queryFn: async (): Promise<{ id: number; name: string }[]> => (await api.get("/v1/products/all-categories")).data,
    staleTime: 60_000,
  });

  const brandOptionsQuery = useQuery({
    queryKey: ["all-brands"],
    queryFn: async (): Promise<{ id: number; name: string }[]> => (await api.get("/v1/products/all-brands")).data,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current);
    if (search.trim().length < 2) { setResults([]); return; }

    searchTimerRef.current = window.setTimeout(async () => {
      setSearching(true);
      try {
        const { data } = await api.get("/v1/products/", { params: { q: search.trim(), limit: 8 } });
        setResults(Array.isArray(data) ? data : []);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);

    return () => { if (searchTimerRef.current !== null) window.clearTimeout(searchTimerRef.current); };
  }, [search]);

  const loadDetailMutation = useMutation({
    mutationFn: async (productId: string): Promise<{ detail: ProductDetail; price: string }> => {
      const detail: ProductDetail = (await api.get(`/v1/products/${productId}`)).data;
      // Pull the current retail price so it prefills the form. Pricing lives on a
      // separate endpoint; tolerate it being missing/empty.
      let price = "";
      try {
        const pricing = (await api.get(`/v1/pricing/${productId}`)).data;
        const retail = Array.isArray(pricing?.prices)
          ? pricing.prices.find((p: { price_type_code?: string }) => p.price_type_code === "RETAIL")
          : null;
        if (retail?.amount != null) price = String(retail.amount);
      } catch {
        // no pricing yet — leave blank
      }
      return { detail, price };
    },
    onSuccess: ({ detail, price }) => {
      setEditingId(detail.id);
      loadedPriceRef.current = price;
      setForm(detailToForm(detail, "", price));
      setBarcodes(detail.barcodes ?? []);
      setMode("edit");
      setStatusMessage(null);
    },
  });

  const unlinkBarcodeMutation = useMutation({
    mutationFn: async ({ productId, barcodeId }: { productId: string; barcodeId: number }) => {
      await api.delete(`/v1/products/${productId}/barcodes/${barcodeId}`);
      return barcodeId;
    },
    onSuccess: (barcodeId) => {
      setBarcodes((current) => current.filter((b) => b.id !== barcodeId));
      setStatusMessage("Barcode unlinked.");
    },
    onError: () => {
      setStatusMessage("Could not unlink barcode.");
    },
  });

  // Open directly in edit mode when the caller (e.g. the scanner) supplies a
  // known product id. Guard with a ref so it only fires once per id.
  useEffect(() => {
    if (!initialEditProductId) return;
    if (loadedEditIdRef.current === initialEditProductId) return;
    loadedEditIdRef.current = initialEditProductId;
    loadDetailMutation.mutate(initialEditProductId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEditProductId]);

  const createMutation = useMutation({
    mutationFn: async (payload: FormState) => {
      const { data } = await api.post("/v1/products/", {
        name: payload.name,
        item_number: payload.item_number || null,
        brand_name: payload.brand_name || null,
        category_name: payload.category_name || null,
        packing: payload.packing || null,
        shot_count: payload.shot_count ? Number(payload.shot_count) : null,
        duration_seconds: payload.duration_seconds ? Number(payload.duration_seconds) : null,
        effects: payload.effects || null,
        description: payload.description || null,
        notes: payload.notes || null,
        barcode: payload.barcode || null,
        in_store: Boolean(flagAsNewInStoreItem),
        needs_data_review: Boolean(flagAsNewInStoreItem),
      });
      const amount = parsePrice(payload.price);
      if (amount != null) {
        await api.put(`/v1/pricing/${data.id}/RETAIL`, { amount, reason: "Set during product entry" });
      }
      return data;
    },
    onSuccess: (data) => {
      setStatusMessage(`Created "${data.name}".`);
      queryClient.invalidateQueries({ queryKey: ["all-categories"] });
      queryClient.invalidateQueries({ queryKey: ["all-brands"] });
      onSaved?.(data.id);
      resetToSearch();
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ productId, payload }: { productId: string; payload: FormState }) => {
      const { data } = await api.patch(`/v1/products/${productId}`, {
        name: payload.name,
        item_number: payload.item_number || null,
        brand_name: payload.brand_name || null,
        category_name: payload.category_name || null,
        packing: payload.packing || null,
        shot_count: payload.shot_count ? Number(payload.shot_count) : null,
        duration_seconds: payload.duration_seconds ? Number(payload.duration_seconds) : null,
        effects: payload.effects || null,
        description: payload.description || null,
        notes: payload.notes || null,
      });
      if (payload.barcode.trim()) {
        await api.post(`/v1/products/${productId}/barcodes`, { barcode: payload.barcode.trim(), is_primary: true });
      }
      // Only touch pricing if the retail price actually changed, to avoid spurious
      // price-history entries on a plain info edit.
      if (payload.price.trim() !== loadedPriceRef.current.trim()) {
        const amount = parsePrice(payload.price);
        if (amount != null) {
          await api.put(`/v1/pricing/${productId}/RETAIL`, { amount, reason: "Updated during product entry" });
        }
      }
      return data;
    },
    onSuccess: (data) => {
      setStatusMessage(`Saved "${data.name}".`);
      onSaved?.(data.id);
      resetToSearch();
    },
  });

  function resetToSearch() {
    setMode("search");
    setEditingId(null);
    setForm(EMPTY_FORM);
    setBarcodes([]);
    loadedPriceRef.current = "";
    setSearch("");
    setResults([]);
  }

  function startCreate() {
    setForm({ ...EMPTY_FORM, barcode: prefillBarcode ?? "" });
    setEditingId(null);
    setBarcodes([]);
    loadedPriceRef.current = "";
    setStatusMessage(null);
    setMode("create");
  }

  function updateField<K extends keyof FormState>(key: K, value: string) {
    setForm((cur) => ({ ...cur, [key]: value }));
  }

  const saving = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="rounded-3xl border border-gray-800 bg-gray-900 p-5 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-xs uppercase tracking-[0.25em] text-gray-400">
          {mode === "search" ? "Manual Product Entry" : mode === "create" ? "New Product" : "Edit Product"}
        </div>
        <div className="flex items-center gap-2">
          {mode !== "search" && (
            <button
              onClick={resetToSearch}
              className="text-xs uppercase tracking-[0.2em] text-gray-500 hover:text-gray-300"
            >
              Back to search
            </button>
          )}
          {onClose && (
            <button onClick={onClose} className="rounded-xl border border-gray-700 bg-gray-950 p-1.5 text-gray-400 hover:text-gray-200">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>

      {statusMessage && (
        <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm text-emerald-200">
          {statusMessage}
        </div>
      )}

      {mode === "search" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                type="text"
                placeholder="Search by name or item number, or use the mic..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-2xl border border-gray-700 bg-gray-950 py-3 pl-10 pr-4 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60 focus:ring-1 focus:ring-orange-500/20"
              />
              {searching && <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-gray-500" />}
            </div>
            <VoiceInputButton onResult={(text) => setSearch(text)} />
          </div>

          {results.length > 0 && (
            <div className="space-y-1">
              {results.map((p) => (
                <button
                  key={p.id}
                  onClick={() => loadDetailMutation.mutate(p.id)}
                  disabled={loadDetailMutation.isPending}
                  className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-4 py-3 text-left transition hover:border-orange-500/40 hover:bg-gray-800 disabled:opacity-50"
                >
                  <div className="flex items-center gap-3">
                    <ProductImage imageUrl={p.image_url} name={p.name} size="xs" />
                    <div className="min-w-0">
                      <div className="font-medium text-gray-100">{p.name}</div>
                      <div className="mt-0.5 text-xs text-gray-500">{p.item_number ?? "No item number"} {p.brand_name ? `· ${p.brand_name}` : ""}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}

          {search.trim().length >= 2 && !searching && results.length === 0 && (
            <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-950 px-4 py-4 text-center text-sm text-gray-500">
              No matching products found.
            </div>
          )}

          <button
            onClick={startCreate}
            className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm font-semibold text-gray-200 transition hover:border-orange-500/50 hover:bg-gray-800"
          >
            <Plus className="h-4 w-4" />
            Add New Product
          </button>
        </div>
      )}

      {(mode === "create" || mode === "edit") && (
        <div className="space-y-3">
          <FieldWithVoice label="Name" value={form.name} onChange={(v) => updateField("name", v)} required />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Retail Price ($)"
              value={form.price}
              onChange={(v) => updateField("price", v)}
              type="number"
              placeholder="e.g. 24.99"
            />
            <Field label="Item Number" value={form.item_number} onChange={(v) => updateField("item_number", v)} />
            <Field label="Packing" value={form.packing} onChange={(v) => updateField("packing", v)} placeholder="e.g. 12/1" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field
              label="Brand"
              value={form.brand_name}
              onChange={(v) => updateField("brand_name", v)}
              listId="brand-options"
              listOptions={brandOptionsQuery.data?.map((b) => b.name) ?? []}
            />
            <Field
              label="Category"
              value={form.category_name}
              onChange={(v) => updateField("category_name", v)}
              listId="category-options"
              listOptions={categoryOptionsQuery.data?.map((c) => c.name) ?? []}
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Shot Count" value={form.shot_count} onChange={(v) => updateField("shot_count", v)} type="number" />
            <Field label="Duration (seconds)" value={form.duration_seconds} onChange={(v) => updateField("duration_seconds", v)} type="number" />
          </div>
          <Field label="Effects" value={form.effects} onChange={(v) => updateField("effects", v)} placeholder="comma-separated tags" />
          <FieldWithVoice label="Description" value={form.description} onChange={(v) => updateField("description", v)} textarea />
          <Field label="Notes" value={form.notes} onChange={(v) => updateField("notes", v)} textarea />

          <div className="rounded-2xl border border-gray-800 bg-gray-950 p-3 space-y-2">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.2em] text-gray-500">
              <BarcodeIcon className="h-3.5 w-3.5" />
              {mode === "create" ? "Barcode (optional)" : "Attach / Replace Barcode (optional)"}
            </div>

            {mode === "edit" && barcodes.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] uppercase tracking-[0.2em] text-gray-600">Linked barcodes</div>
                {barcodes.map((b) => (
                  <div
                    key={b.id}
                    className="flex items-center justify-between gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2"
                  >
                    <div className="min-w-0">
                      <span className="font-mono text-sm text-gray-100">{b.barcode}</span>
                      {b.is_primary && (
                        <span className="ml-2 rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-orange-200">
                          Primary
                        </span>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        if (editingId) unlinkBarcodeMutation.mutate({ productId: editingId, barcodeId: b.id });
                      }}
                      disabled={unlinkBarcodeMutation.isPending}
                      title="Unlink this barcode from the product"
                      className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/5 px-2.5 py-1.5 text-xs font-semibold text-red-200 transition hover:bg-red-500/15 disabled:opacity-50"
                    >
                      <X className="h-3.5 w-3.5" />
                      Unlink
                    </button>
                  </div>
                ))}
              </div>
            )}

            <input
              type="text"
              placeholder="Scan or type barcode..."
              value={form.barcode}
              onChange={(e) => updateField("barcode", e.target.value)}
              className="w-full rounded-xl border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60"
            />
          </div>

          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={() => {
                if (!form.name.trim()) { setStatusMessage("Name is required."); return; }
                if (form.price.trim() && parsePrice(form.price) == null) {
                  setStatusMessage("Price must be a number of 0 or more.");
                  return;
                }
                if (mode === "create") createMutation.mutate(form);
                else if (editingId) updateMutation.mutate({ productId: editingId, payload: form });
              }}
              disabled={saving}
              className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-5 py-2.5 text-sm font-semibold text-gray-950 transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "create" ? "Create Product" : "Save Changes"}
            </button>
            <button
              onClick={resetToSearch}
              className="rounded-2xl border border-gray-800 bg-gray-950 px-5 py-2.5 text-sm font-semibold text-gray-300 hover:border-gray-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  textarea = false,
  listId,
  listOptions,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  textarea?: boolean;
  listId?: string;
  listOptions?: string[];
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] uppercase tracking-[0.2em] text-gray-500">{label}</span>
      {textarea ? (
        <textarea
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          className="w-full resize-none rounded-xl border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60"
        />
      ) : (
        <>
          <input
            type={type}
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            list={listId}
            className="w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60"
          />
          {listId && listOptions && (
            <datalist id={listId}>
              {listOptions.map((option) => (
                <option key={option} value={option} />
              ))}
            </datalist>
          )}
        </>
      )}
    </label>
  );
}

function FieldWithVoice({
  label,
  value,
  onChange,
  placeholder,
  required = false,
  textarea = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  textarea?: boolean;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] uppercase tracking-[0.2em] text-gray-500">
        {label}
        {required ? " *" : ""}
      </span>
      <div className="flex items-start gap-2">
        {textarea ? (
          <textarea
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            rows={2}
            className="w-full resize-none rounded-xl border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60"
          />
        ) : (
          <input
            type="text"
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            className="w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 outline-none focus:border-orange-500/60"
          />
        )}
        <VoiceInputButton onResult={(text) => onChange(value ? `${value} ${text}` : text)} />
      </div>
    </label>
  );
}
