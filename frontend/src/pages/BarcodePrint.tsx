import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import ProductImage from "../components/ProductImage";

type Product = {
  id: string;
  name: string;
  item_number: string | null;
  image_url: string | null;
};

type QueueItem = Product & {
  copies: number;
};

type TemplateKey = "avery5160" | "avery5163" | "avery5167";
type LabelSize = "small" | "medium" | "large";

const SHEET_TEMPLATES: { key: TemplateKey; label: string; capacity: number }[] = [
  { key: "avery5160", label: "Avery 5160 30-up", capacity: 30 },
  { key: "avery5163", label: "Avery 5163 10-up", capacity: 10 },
  { key: "avery5167", label: "Avery 5167 80-up", capacity: 80 },
];

const LABEL_SIZES: { key: LabelSize; label: string }[] = [
  { key: "small", label: "Small 2x1" },
  { key: "medium", label: "Medium 3x2" },
  { key: "large", label: "Large 4x3" },
];

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

function formatCount(count: number) {
  return count.toLocaleString();
}

export default function BarcodePrint() {
  const [tab, setTab] = useState<"sheet" | "label">("sheet");

  const [sheetQuery, setSheetQuery] = useState("");
  const [sheetResults, setSheetResults] = useState<Product[]>([]);
  const [sheetQueue, setSheetQueue] = useState<QueueItem[]>([]);
  const [sheetLoading, setSheetLoading] = useState(false);
  const [sheetTemplate, setSheetTemplate] = useState<TemplateKey>("avery5160");
  const [sheetShowName, setSheetShowName] = useState(true);
  const [sheetShowPrice, setSheetShowPrice] = useState(false);

  const [labelQuery, setLabelQuery] = useState("");
  const [labelResults, setLabelResults] = useState<Product[]>([]);
  const [selectedLabelProduct, setSelectedLabelProduct] = useState<Product | null>(null);
  const [labelLoading, setLabelLoading] = useState(false);
  const [labelSize, setLabelSize] = useState<LabelSize>("medium");
  const [labelCopies, setLabelCopies] = useState(1);
  const [labelShowName, setLabelShowName] = useState(true);
  const [labelShowPrice, setLabelShowPrice] = useState(false);

  useEffect(() => {
    const query = sheetQuery.trim();
    if (!query) {
      setSheetResults([]);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSheetLoading(true);
      try {
        const { data } = await axios.get<Product[]>("/api/v1/products/", {
          params: { q: query, limit: 20 },
          signal: controller.signal,
        });
        setSheetResults(data);
      } catch {
        if (!controller.signal.aborted) {
          setSheetResults([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setSheetLoading(false);
        }
      }
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [sheetQuery]);

  useEffect(() => {
    const query = labelQuery.trim();
    if (!query) {
      setLabelResults([]);
      return;
    }

    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLabelLoading(true);
      try {
        const { data } = await axios.get<Product[]>("/api/v1/products/", {
          params: { q: query, limit: 20 },
          signal: controller.signal,
        });
        setLabelResults(data);
      } catch {
        if (!controller.signal.aborted) {
          setLabelResults([]);
        }
      } finally {
        if (!controller.signal.aborted) {
          setLabelLoading(false);
        }
      }
    }, 250);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [labelQuery]);

  const sheetTotalLabels = useMemo(
    () => sheetQueue.reduce((sum, item) => sum + item.copies, 0),
    [sheetQueue]
  );

  const sheetPages = useMemo(() => {
    const capacity = SHEET_TEMPLATES.find((template) => template.key === sheetTemplate)?.capacity ?? 30;
    if (sheetTotalLabels === 0) return 0;
    return Math.ceil(sheetTotalLabels / capacity);
  }, [sheetTemplate, sheetTotalLabels]);

  function addToSheetQueue(product: Product) {
    setSheetQueue((current) => {
      if (current.some((item) => item.id === product.id)) return current;
      return [...current, { ...product, copies: 1 }];
    });
  }

  function updateSheetCopies(productId: string, delta: number) {
    setSheetQueue((current) =>
      current.map((item) =>
        item.id === productId
          ? { ...item, copies: clamp(item.copies + delta, 1, 10) }
          : item
      )
    );
  }

  function removeSheetItem(productId: string) {
    setSheetQueue((current) => current.filter((item) => item.id !== productId));
  }

  function openSheetPdf() {
    if (!sheetQueue.length) return;
    const params = new URLSearchParams();
    params.set(
      "product_ids",
      sheetQueue.flatMap((item) => Array.from({ length: item.copies }, () => item.id)).join(",")
    );
    params.set("copies", "1");
    params.set("template", sheetTemplate);
    params.set("show_name", String(sheetShowName));
    params.set("show_price", String(sheetShowPrice));
    window.open(`/api/v1/barcodes/sheet?${params.toString()}`, "_blank", "noopener,noreferrer");
  }

  function openLabelPdf() {
    if (!selectedLabelProduct) return;
    const params = new URLSearchParams({
      size: labelSize,
      copies: String(clamp(labelCopies, 1, 100)),
      show_name: String(labelShowName),
      show_price: String(labelShowPrice),
    });
    window.open(
      `/api/v1/barcodes/label/${selectedLabelProduct.id}?${params.toString()}`,
      "_blank",
      "noopener,noreferrer"
    );
  }

  const sheetPreview = sheetQueue[0];

  return (
    <div className="min-h-full bg-gradient-to-br from-gray-950 via-gray-950 to-gray-900 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/90 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Barcode Printing</h1>
            <p className="mt-1 text-sm text-gray-400">
              Build label sheets and one-off labels from active products.
            </p>
          </div>
          <div className="inline-flex rounded-lg border border-gray-800 bg-gray-900 p-1">
            {[
              { key: "sheet", label: "Sheet Print" },
              { key: "label", label: "Label Print" },
            ].map((item) => (
              <button
                key={item.key}
                onClick={() => setTab(item.key as "sheet" | "label")}
                className={`rounded-md px-4 py-2 text-sm transition ${
                  tab === item.key
                    ? "bg-orange-500 text-white shadow"
                    : "text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tab === "sheet" ? (
        <div className="grid gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[1.4fr_0.9fr]">
          <section className="space-y-6">
            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Search products
                  </label>
                  <input
                    value={sheetQuery}
                    onChange={(e) => setSheetQuery(e.target.value)}
                    placeholder="Search by name or item number"
                    className="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-orange-500"
                  />
                </div>
                <div className="pb-1 text-xs text-gray-500">
                  {sheetLoading ? "Searching..." : `${sheetResults.length} results`}
                </div>
              </div>

              {sheetResults.length > 0 && (
                <div className="mt-4 grid gap-2">
                  {sheetResults.map((product) => (
                    <button
                      key={product.id}
                      onClick={() => addToSheetQueue(product)}
                      className="flex items-center justify-between gap-3 rounded-xl border border-gray-800 bg-gray-950/80 px-4 py-3 text-left transition hover:border-orange-500/60 hover:bg-gray-800"
                    >
                      <div className="flex items-center gap-3">
                        <ProductImage imageUrl={product.image_url} name={product.name} size="xs" />
                        <div>
                          <div className="font-medium text-gray-100">{product.name}</div>
                          <div className="mt-1 text-xs text-gray-500">{product.item_number || "No item number"}</div>
                        </div>
                      </div>
                      <div className="rounded-full border border-orange-500/40 px-3 py-1 text-sm text-orange-300">
                        +
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">Print queue</h2>
                <div className="text-sm text-gray-500">
                  {formatCount(sheetTotalLabels)} labels
                </div>
              </div>

              <div className="mt-4 space-y-3">
                {sheetQueue.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-gray-700 px-4 py-8 text-center text-sm text-gray-500">
                    Add products to build a sheet.
                  </div>
                ) : (
                  sheetQueue.map((item) => (
                    <div
                      key={item.id}
                      className="grid gap-4 rounded-xl border border-gray-800 bg-gray-950/70 p-4 md:grid-cols-[1fr_220px]"
                    >
                      <div className="space-y-2">
                        <div>
                          <div className="font-medium text-gray-100">{item.name}</div>
                          <div className="text-xs text-gray-500">{item.item_number || "No item number"}</div>
                        </div>
                        <div className="inline-flex items-center rounded-lg border border-gray-800 bg-gray-900 px-2 py-1 text-xs text-gray-400">
                          Copies
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => updateSheetCopies(item.id, -1)}
                            className="h-9 w-9 rounded-lg border border-gray-700 bg-gray-900 text-lg hover:bg-gray-800"
                          >
                            -
                          </button>
                          <span className="min-w-[2.5rem] text-center text-sm font-semibold">{item.copies}</span>
                          <button
                            onClick={() => updateSheetCopies(item.id, 1)}
                            className="h-9 w-9 rounded-lg border border-gray-700 bg-gray-900 text-lg hover:bg-gray-800"
                          >
                            +
                          </button>
                          <button
                            onClick={() => removeSheetItem(item.id)}
                            className="ml-2 rounded-lg border border-red-500/40 px-3 py-2 text-xs text-red-300 hover:bg-red-500/10"
                          >
                            Remove
                          </button>
                        </div>
                      </div>

                      <div className="flex items-center justify-center rounded-xl border border-gray-800 bg-white p-3">
                        <img
                          src={`/api/v1/barcodes/preview/${item.id}?width=360`}
                          alt={`${item.name} barcode preview`}
                          className="max-h-28 w-full object-contain"
                        />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <aside className="space-y-6">
            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">Options</h2>

              <div className="mt-4 space-y-4">
                <label className="block">
                  <span className="mb-2 block text-xs uppercase tracking-wide text-gray-500">Template</span>
                  <select
                    value={sheetTemplate}
                    onChange={(e) => setSheetTemplate(e.target.value as TemplateKey)}
                    className="w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-3 text-sm outline-none focus:border-orange-500"
                  >
                    {SHEET_TEMPLATES.map((template) => (
                      <option key={template.key} value={template.key}>
                        {template.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-950 px-4 py-3">
                  <span className="text-sm text-gray-200">Show product name</span>
                  <input
                    type="checkbox"
                    checked={sheetShowName}
                    onChange={(e) => setSheetShowName(e.target.checked)}
                    className="h-4 w-4 accent-orange-500"
                  />
                </label>

                <label className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-950 px-4 py-3">
                  <span className="text-sm text-gray-200">Show price</span>
                  <input
                    type="checkbox"
                    checked={sheetShowPrice}
                    onChange={(e) => setSheetShowPrice(e.target.checked)}
                    className="h-4 w-4 accent-orange-500"
                  />
                </label>

                <div className="rounded-xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-300">
                  {formatCount(sheetTotalLabels)} labels across {formatCount(sheetPages)} page
                  {sheetPages === 1 ? "" : "s"}
                </div>

                <button
                  onClick={openSheetPdf}
                  disabled={!sheetQueue.length}
                  className="w-full rounded-xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                >
                  Generate Sheet
                </button>
              </div>
            </div>

            {sheetPreview && (
              <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">First preview</h2>
                <div className="mt-4 rounded-xl border border-gray-800 bg-white p-3">
                  <img
                    src={`/api/v1/barcodes/preview/${sheetPreview.id}?width=600`}
                    alt={sheetPreview.name}
                    className="h-40 w-full object-contain"
                  />
                </div>
              </div>
            )}
          </aside>
        </div>
      ) : (
        <div className="grid gap-6 px-4 py-6 sm:px-6 xl:grid-cols-[1.2fr_0.8fr]">
          <section className="space-y-6">
            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label className="mb-2 block text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Search product
                  </label>
                  <input
                    value={labelQuery}
                    onChange={(e) => setLabelQuery(e.target.value)}
                    placeholder="Search by name or item number"
                    className="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm text-gray-100 outline-none transition placeholder:text-gray-600 focus:border-orange-500"
                  />
                </div>
                <div className="pb-1 text-xs text-gray-500">
                  {labelLoading ? "Searching..." : `${labelResults.length} results`}
                </div>
              </div>

              {labelResults.length > 0 && (
                <div className="mt-4 grid gap-2">
                  {labelResults.map((product) => (
                    <button
                      key={product.id}
                      onClick={() => setSelectedLabelProduct(product)}
                      className="flex items-center justify-between gap-3 rounded-xl border border-gray-800 bg-gray-950/80 px-4 py-3 text-left transition hover:border-orange-500/60 hover:bg-gray-800"
                    >
                      <div>
                        <div className="font-medium text-gray-100">{product.name}</div>
                        <div className="mt-1 text-xs text-gray-500">{product.item_number || "No item number"}</div>
                      </div>
                      <div className="rounded-full border border-orange-500/40 px-3 py-1 text-sm text-orange-300">
                        Select
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">Selected product</h2>
                {selectedLabelProduct && (
                  <button
                    onClick={() => setSelectedLabelProduct(null)}
                    className="text-xs text-gray-500 hover:text-gray-200"
                  >
                    Clear
                  </button>
                )}
              </div>

              {!selectedLabelProduct ? (
                <div className="mt-4 rounded-xl border border-dashed border-gray-700 px-4 py-10 text-center text-sm text-gray-500">
                  Select one product to print a label.
                </div>
              ) : (
                <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_240px]">
                  <div className="space-y-3">
                    <div>
                      <div className="text-lg font-semibold text-gray-100">{selectedLabelProduct.name}</div>
                      <div className="text-sm text-gray-500">{selectedLabelProduct.item_number || "No item number"}</div>
                    </div>
                    <div className="rounded-2xl border border-gray-800 bg-white p-4">
                      <img
                        src={`/api/v1/barcodes/preview/${selectedLabelProduct.id}?width=700`}
                        alt={selectedLabelProduct.name}
                        className="h-52 w-full object-contain"
                      />
                    </div>
                  </div>

                  <div className="space-y-4 rounded-2xl border border-gray-800 bg-gray-950/70 p-4">
                    <label className="block">
                      <span className="mb-2 block text-xs uppercase tracking-wide text-gray-500">Size</span>
                      <select
                        value={labelSize}
                        onChange={(e) => setLabelSize(e.target.value as LabelSize)}
                        className="w-full rounded-xl border border-gray-700 bg-gray-950 px-3 py-3 text-sm outline-none focus:border-orange-500"
                      >
                        {LABEL_SIZES.map((size) => (
                          <option key={size.key} value={size.key}>
                            {size.label}
                          </option>
                        ))}
                      </select>
                    </label>

                    <div>
                      <span className="mb-2 block text-xs uppercase tracking-wide text-gray-500">Copies</span>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setLabelCopies((value) => clamp(value - 1, 1, 100))}
                          className="h-10 w-10 rounded-lg border border-gray-700 bg-gray-900 text-lg hover:bg-gray-800"
                        >
                          -
                        </button>
                        <div className="min-w-[3rem] rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-center text-sm">
                          {labelCopies}
                        </div>
                        <button
                          onClick={() => setLabelCopies((value) => clamp(value + 1, 1, 100))}
                          className="h-10 w-10 rounded-lg border border-gray-700 bg-gray-900 text-lg hover:bg-gray-800"
                        >
                          +
                        </button>
                      </div>
                    </div>

                    <label className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-900 px-4 py-3">
                      <span className="text-sm text-gray-200">Show product name</span>
                      <input
                        type="checkbox"
                        checked={labelShowName}
                        onChange={(e) => setLabelShowName(e.target.checked)}
                        className="h-4 w-4 accent-orange-500"
                      />
                    </label>

                    <label className="flex items-center justify-between rounded-xl border border-gray-800 bg-gray-900 px-4 py-3">
                      <span className="text-sm text-gray-200">Show price</span>
                      <input
                        type="checkbox"
                        checked={labelShowPrice}
                        onChange={(e) => setLabelShowPrice(e.target.checked)}
                        className="h-4 w-4 accent-orange-500"
                      />
                    </label>

                    <button
                      onClick={openLabelPdf}
                      className="w-full rounded-xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400"
                    >
                      Print Label
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <aside className="space-y-6">
            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">How it works</h2>
              <ul className="mt-4 space-y-3 text-sm leading-6 text-gray-300">
                <li>Search products by name or item number.</li>
                <li>Sheet print builds a queue and sends the selected template to the PDF endpoint.</li>
                <li>Label print targets one product and repeats it across the requested number of pages.</li>
              </ul>
            </div>

            <div className="rounded-2xl border border-gray-800 bg-gray-900/70 p-5 shadow-xl shadow-black/20">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-400">Preview</h2>
              <div className="mt-4 rounded-xl border border-gray-800 bg-white p-3">
                {selectedLabelProduct ? (
                  <img
                    src={`/api/v1/barcodes/preview/${selectedLabelProduct.id}?width=500`}
                    alt="Barcode preview"
                    className="h-44 w-full object-contain"
                  />
                ) : (
                  <div className="flex h-44 items-center justify-center text-sm text-gray-500">
                    No product selected
                  </div>
                )}
              </div>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
