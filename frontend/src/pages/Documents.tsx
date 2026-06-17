import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download, File, FileArchive, FileImage, FileSpreadsheet, FileText,
  Globe, Loader2, PackageSearch, Trash2, Upload, X, ChevronRight, AlertCircle,
} from "lucide-react";

// ─── Types ──────────────────────────────────────────────────────────────────

type DocumentRecord = {
  id: number; name: string; category: string; file_path: string;
  file_size: number | null; mime_type: string | null; notes: string | null;
  uploaded_at: string; supplier_name: string | null; doc_date: string | null;
};

type ImportJob = {
  job_id: number; status: string; created_at: string;
  completed_at: string | null; error_message: string | null;
  document_type: string; file_name: string;
  row_counts: Record<string, number> | null;
};

type ImportRow = {
  id: number; job_id: number; row_index: number; raw_data: Record<string, unknown>;
  matched_product_id: string | null; match_confidence: number | null;
  review_status: string; reviewed_at: string | null; notes: string | null;
};

type RowDraft = {
  name: string; item_code: string; brand: string; price: string;
  shot_count: string; description: string; category: string; packing: string;
};

type IssuuScrapeResult = {
  job_id: number; status: string; message: string;
};

// ─── Constants ───────────────────────────────────────────────────────────────

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });
const DOC_CATEGORIES = ["Invoices", "Catalogs", "Sale Orders", "Price Lists", "Other"] as const;

type SidebarView = "All" | typeof DOC_CATEGORIES[number] | "imports";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatBytes(size: number | null) {
  if (!size) return "—";
  if (size < 1024) return `${size} B`;
  const units = ["KB", "MB", "GB"];
  let v = size / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v >= 10 ? 0 : 1)} ${units[i]}`;
}

function formatDate(v: string | null | undefined) {
  if (!v) return "—";
  return new Date(v).toLocaleDateString();
}

function isPdf(doc: DocumentRecord) {
  return (doc.mime_type ?? "").includes("pdf") || doc.file_path.endsWith(".pdf");
}

function fileIcon(doc: DocumentRecord) {
  const m = (doc.mime_type ?? "").toLowerCase();
  if (m.includes("pdf")) return <FileText className="h-5 w-5 text-red-300" />;
  if (m.includes("spreadsheet") || m.includes("excel") || /\.(xls|xlsx|csv)$/.test(doc.file_path))
    return <FileSpreadsheet className="h-5 w-5 text-emerald-300" />;
  if (m.startsWith("image/")) return <FileImage className="h-5 w-5 text-cyan-300" />;
  if (m.includes("zip") || /\.(zip|rar|7z)$/.test(doc.file_path))
    return <FileArchive className="h-5 w-5 text-amber-300" />;
  return <File className="h-5 w-5 text-gray-300" />;
}

function statusTone(s: string) {
  if (s === "done") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (s === "failed") return "border-red-500/30 bg-red-500/10 text-red-300";
  if (s === "review") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (s === "running" || s === "pending") return "border-blue-500/30 bg-blue-500/10 text-blue-300";
  return "border-gray-700 bg-gray-900 text-gray-400";
}

function extractCdnId(url: string): string | null {
  // https://issuu.com/cloudsent/docs/... or raw CDN ID
  const docMatch = url.match(/issuu\.com\/[^/]+\/docs\/([^/?#]+)/);
  if (docMatch) return null; // need API to resolve — return null, backend handles URL
  // Already looks like a CDN ID (hex string with dashes)
  if (/^\d{12}-[a-f0-9]{32}$/.test(url.trim())) return url.trim();
  return null;
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function Documents() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);

  // Sidebar / view state
  const [view, setView] = useState<SidebarView>("All");

  // Document state
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadCategory, setUploadCategory] = useState("Other");
  const [uploadSupplier, setUploadSupplier] = useState("");
  const [uploadDate, setUploadDate] = useState("");
  const [uploadNotes, setUploadNotes] = useState("");
  const [uploadName, setUploadName] = useState("");

  // Import state
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [issuuUrl, setIssuuUrl] = useState("");
  const [issuuSlug, setIssuuSlug] = useState("");
  const [issuuYear, setIssuuYear] = useState(new Date().getFullYear().toString());
  const [drafts, setDrafts] = useState<Record<number, RowDraft>>({});

  // ── Queries ─────────────────────────────────────────────────────────────────

  const docsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: async (): Promise<DocumentRecord[]> => (await api.get("/v1/documents/")).data,
  });

  const jobsQuery = useQuery({
    queryKey: ["import-jobs"],
    queryFn: async (): Promise<ImportJob[]> => (await api.get("/v1/imports/")).data,
    enabled: view === "imports",
    refetchInterval: (q) => {
      const jobs: ImportJob[] = q.state.data ?? [];
      return jobs.some(j => j.status === "pending" || j.status === "running") ? 3000 : false;
    },
  });

  const activeJobQuery = useQuery({
    queryKey: ["import-job", activeJobId],
    queryFn: async (): Promise<ImportJob> => (await api.get(`/v1/imports/${activeJobId}`)).data,
    enabled: activeJobId !== null,
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s && s !== "done" && s !== "failed" ? 2000 : false;
    },
  });

  const rowsQuery = useQuery({
    queryKey: ["import-rows", activeJobId],
    queryFn: async () => {
      const { data } = await api.get(`/v1/imports/${activeJobId}/rows`, {
        params: { status: "pending", page: 1, per_page: 200 },
      });
      return data as { items: ImportRow[]; total: number };
    },
    enabled: activeJobId !== null && activeJobQuery.data?.status === "review",
  });

  useEffect(() => {
    if (!rowsQuery.data?.items) return;
    const next: Record<number, RowDraft> = {};
    for (const row of rowsQuery.data.items) {
      const r = row.raw_data ?? {};
      next[row.id] = {
        name: String(r.name ?? ""), item_code: String(r.item_code ?? ""),
        brand: String(r.brand ?? ""), price: String(r.price ?? ""),
        shot_count: String(r.shot_count ?? ""), description: String(r.description ?? ""),
        category: String(r.category ?? ""), packing: String(r.packing ?? ""),
      };
    }
    setDrafts(prev => ({ ...prev, ...next }));
  }, [rowsQuery.data]);

  // ── Mutations ────────────────────────────────────────────────────────────────

  const uploadDocMutation = useMutation({
    mutationFn: async () => {
      if (!uploadFile) throw new Error("No file");
      const fd = new FormData();
      fd.append("file", uploadFile);
      fd.append("name", uploadName || uploadFile.name);
      fd.append("category", uploadCategory);
      if (uploadSupplier) fd.append("supplier_name", uploadSupplier);
      if (uploadDate) fd.append("doc_date", uploadDate);
      if (uploadNotes) fd.append("notes", uploadNotes);
      return (await api.post("/v1/documents/upload", fd, { headers: { "Content-Type": "multipart/form-data" } })).data as DocumentRecord;
    },
    onSuccess: async (doc) => {
      closeUploadModal();
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setSelectedDocId(doc.id);
    },
  });

  const deleteDocMutation = useMutation({
    mutationFn: async (id: number) => { await api.delete(`/v1/documents/${id}`); return id; },
    onSuccess: async (id) => {
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      if (selectedDocId === id) setSelectedDocId(null);
    },
  });

  const pdfImportMutation = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData(); fd.append("pdf", file);
      return (await api.post("/v1/imports/pdf", fd, { headers: { "Content-Type": "multipart/form-data" } })).data as { job_id: number };
    },
    onSuccess: async (data) => {
      setActiveJobId(data.job_id);
      await queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    },
  });

  const issuuImportMutation = useMutation({
    mutationFn: async () => {
      return (await api.post("/v1/imports/issuu", {
        url: issuuUrl.trim(),
        slug: issuuSlug.trim() || undefined,
        year: issuuYear.trim() || undefined,
      })).data as IssuuScrapeResult;
    },
    onSuccess: async (data) => {
      setActiveJobId(data.job_id);
      setIssuuUrl("");
      await queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    },
  });

  const rowMutation = useMutation({
    mutationFn: async ({ row, status }: { row: ImportRow; status: string }) => {
      const d = drafts[row.id] ?? {};
      return (await api.patch(`/v1/imports/${activeJobId}/rows/${row.id}`, {
        name: d.name, item_code: d.item_code, brand: d.brand,
        price: d.price === "" ? null : Number(d.price),
        shot_count: d.shot_count === "" ? null : Number(d.shot_count),
        description: d.description, category: d.category, packing: d.packing,
        review_status: status,
      })).data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-job", activeJobId] });
      await queryClient.invalidateQueries({ queryKey: ["import-rows", activeJobId] });
    },
  });

  const commitMutation = useMutation({
    mutationFn: async () => (await api.post(`/v1/imports/${activeJobId}/commit`)).data,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-job", activeJobId] });
      await queryClient.invalidateQueries({ queryKey: ["import-jobs"] });
    },
  });

  // ── Derived state ─────────────────────────────────────────────────────────────

  const docs = docsQuery.data ?? [];
  const catCounts = useMemo(() => {
    const m = new Map<string, number>(DOC_CATEGORIES.map(c => [c, 0]));
    for (const d of docs) m.set(d.category || "Other", (m.get(d.category || "Other") ?? 0) + 1);
    return m;
  }, [docs]);
  const filteredDocs = view === "imports" || view === "All" ? docs : docs.filter(d => d.category === view);
  const selectedDoc = docs.find(d => d.id === selectedDocId) ?? null;
  const jobs = jobsQuery.data ?? [];
  const activeJob = activeJobQuery.data ?? null;
  const pendingRows = rowsQuery.data?.items ?? [];
  const jobStatus = activeJob?.status ?? "idle";

  // ── Upload modal helpers ──────────────────────────────────────────────────────

  function closeUploadModal() {
    setUploadOpen(false); setUploadFile(null); setUploadSupplier(""); setUploadDate("");
    setUploadNotes(""); setUploadName(""); setUploadCategory("Other");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function pickFile(f: File | null) {
    if (!f) return;
    setUploadFile(f);
    setUploadName(prev => prev || f.name.replace(/\.[^.]+$/, ""));
  }

  function onDropDoc(e: DragEvent<HTMLDivElement>) {
    e.preventDefault(); setDragActive(false);
    pickFile(e.dataTransfer.files?.[0] ?? null);
  }

  function updateDraft(rowId: number, key: keyof RowDraft, value: string) {
    setDrafts(prev => ({ ...prev, [rowId]: { ...(prev[rowId] ?? {} as RowDraft), [key]: value } }));
  }

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      {/* Header */}
      <div className="border-b border-gray-800 bg-gray-950/95 px-6 py-4 backdrop-blur">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Documents & Imports</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {view === "imports" ? "Catalog Imports" : "Store Documents"}
            </h1>
          </div>
          <div className="flex gap-2">
            {view !== "imports" && (
              <button
                onClick={() => setUploadOpen(true)}
                className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 transition"
              >
                <Upload className="h-4 w-4" /> Upload Document
              </button>
            )}
            {view === "imports" && (
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 transition">
                <Upload className="h-4 w-4" /> Upload PDF Catalog
                <input ref={pdfInputRef} type="file" accept="application/pdf" className="hidden"
                  onChange={e => { const f = e.target.files?.[0]; if (f) pdfImportMutation.mutate(f); }} />
              </label>
            )}
          </div>
        </div>
      </div>

      <div className="flex min-h-[calc(100vh-81px)] flex-col lg:flex-row">
        {/* Sidebar */}
        <aside className="w-full shrink-0 space-y-1 border-b border-gray-800 bg-gray-900/90 px-4 py-5 lg:w-56 lg:border-b-0 lg:border-r">
          <div className="mb-3 text-[11px] uppercase tracking-[0.25em] text-gray-600">Documents</div>
          <SidebarBtn active={view === "All"} onClick={() => setView("All")} label="All" count={docs.length} />
          {DOC_CATEGORIES.map(cat => (
            <SidebarBtn key={cat} active={view === cat} onClick={() => setView(cat)} label={cat} count={catCounts.get(cat) ?? 0} />
          ))}
          <div className="mt-5 mb-3 border-t border-gray-800 pt-4 text-[11px] uppercase tracking-[0.25em] text-gray-600">Catalog Import</div>
          <SidebarBtn
            active={view === "imports"}
            onClick={() => { setView("imports"); queryClient.invalidateQueries({ queryKey: ["import-jobs"] }); }}
            label="Import Jobs"
            count={jobs.length}
            icon={<PackageSearch className="h-3.5 w-3.5" />}
          />
        </aside>

        {/* Main content */}
        <main className="flex-1 overflow-hidden">
          {view !== "imports" ? (
            // ── Document file explorer ──────────────────────────────────────
            <div className="grid h-full grid-cols-1 lg:grid-cols-[minmax(0,1.3fr)_360px]">
              <section className="overflow-auto px-4 py-6 sm:px-6">
                {docsQuery.isLoading ? (
                  <LoadingCard text="Loading documents..." />
                ) : (
                  <div className="space-y-3">
                    <div className="space-y-3 lg:hidden">
                      {filteredDocs.map((doc) => (
                        <div
                          key={doc.id}
                          onClick={() => setSelectedDocId(doc.id)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              setSelectedDocId(doc.id);
                            }
                          }}
                          className={`w-full rounded-3xl border p-4 text-left transition ${
                            doc.id === selectedDocId
                              ? "border-orange-500 bg-orange-500/10"
                              : "border-gray-800 bg-gray-900 hover:border-gray-700 hover:bg-gray-800/50"
                          }`}
                        >
                          <div className="flex items-start gap-3">
                            {fileIcon(doc)}
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-sm font-medium text-gray-50">{doc.name}</div>
                              <div className="mt-1 text-xs text-gray-500">{doc.mime_type || "Unknown type"}</div>
                            </div>
                          </div>
                          <div className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                            <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Category</div>
                              <div className="mt-1 text-gray-100">{doc.category}</div>
                            </div>
                            <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Size</div>
                              <div className="mt-1 text-gray-100">{formatBytes(doc.file_size)}</div>
                            </div>
                            <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Supplier</div>
                              <div className="mt-1 text-gray-100">{doc.supplier_name || "—"}</div>
                            </div>
                            <div className="rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2">
                              <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">Date</div>
                              <div className="mt-1 text-gray-100">{formatDate(doc.doc_date)}</div>
                            </div>
                          </div>
                          <div className="mt-4 flex flex-wrap gap-2" onClick={(event) => event.stopPropagation()}>
                            <button
                              onClick={() => window.open(`${apiBase}/v1/documents/${doc.id}/download`, "_blank", "noopener")}
                              className="inline-flex items-center gap-1 rounded-xl border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-200 hover:bg-gray-900"
                            >
                              <Download className="h-3.5 w-3.5" />
                              Download
                            </button>
                            <button
                              onClick={() => {
                                if (window.confirm("Delete this document?")) deleteDocMutation.mutate(doc.id);
                              }}
                              className="inline-flex items-center gap-1 rounded-xl border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-200 hover:bg-red-500/10"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Delete
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>

                    <div className="hidden overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 lg:block">
                      <table className="min-w-full divide-y divide-gray-800">
                      <thead className="bg-gray-950">
                        <tr className="text-left text-[11px] uppercase tracking-[0.2em] text-gray-500">
                          <th className="px-4 py-3">Name</th>
                          <th className="px-4 py-3">Category</th>
                          <th className="px-4 py-3">Supplier</th>
                          <th className="px-4 py-3">Date</th>
                          <th className="px-4 py-3">Size</th>
                          <th className="px-4 py-3">Actions</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-800">
                        {filteredDocs.map(doc => (
                          <tr key={doc.id} onClick={() => setSelectedDocId(doc.id)}
                            className={`cursor-pointer transition ${doc.id === selectedDocId ? "bg-orange-500/5" : "hover:bg-gray-800/40"}`}>
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-3">
                                {fileIcon(doc)}
                                <div>
                                  <div className="font-medium text-gray-50 text-sm">{doc.name}</div>
                                  <div className="text-xs text-gray-500">{doc.mime_type || "Unknown type"}</div>
                                </div>
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-xs text-gray-300">{doc.category}</span>
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-300">{doc.supplier_name || "—"}</td>
                            <td className="px-4 py-3 text-sm text-gray-300">{formatDate(doc.doc_date)}</td>
                            <td className="px-4 py-3 text-sm text-gray-300">{formatBytes(doc.file_size)}</td>
                            <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                              <div className="flex gap-2">
                                <button onClick={() => window.open(`${apiBase}/v1/documents/${doc.id}/download`, "_blank", "noopener")}
                                  className="inline-flex items-center gap-1 rounded-xl border border-gray-800 bg-gray-950 px-2.5 py-1.5 text-xs text-gray-200 hover:bg-gray-900">
                                  <Download className="h-3.5 w-3.5" /> Download
                                </button>
                                <button onClick={() => { if (window.confirm("Delete this document?")) deleteDocMutation.mutate(doc.id); }}
                                  className="inline-flex items-center gap-1 rounded-xl border border-red-500/30 bg-red-500/5 px-2.5 py-1.5 text-xs text-red-200 hover:bg-red-500/10">
                                  <Trash2 className="h-3.5 w-3.5" /> Delete
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                        {filteredDocs.length === 0 && (
                          <tr><td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-500">No documents in this category.</td></tr>
                        )}
                      </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </section>

              <aside className="border-t border-gray-800 bg-gray-900/70 px-4 py-6 lg:border-l lg:border-t-0 lg:px-5">
                {!selectedDoc ? (
                  <EmptyCard text="Select a document to preview it." />
                ) : isPdf(selectedDoc) ? (
                  <div className="space-y-4">
                    <div className="rounded-3xl border border-gray-800 bg-gray-950 p-4">
                      <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Preview</div>
                      <div className="mt-2 text-xl font-semibold text-gray-50">{selectedDoc.name}</div>
                      <div className="mt-1 text-sm text-gray-400">{selectedDoc.category}</div>
                    </div>
                    <div className="overflow-hidden rounded-3xl border border-gray-800 bg-gray-950">
                      <iframe title={selectedDoc.name} src={`${apiBase}/v1/documents/${selectedDoc.id}/download`}
                        className="h-[calc(100vh-210px)] w-full" />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4 rounded-3xl border border-gray-800 bg-gray-950 p-5">
                    <div className="flex items-center gap-3">
                      {fileIcon(selectedDoc)}
                      <div>
                        <div className="text-lg font-semibold text-gray-50">{selectedDoc.name}</div>
                        <div className="text-sm text-gray-400">{selectedDoc.mime_type || "Unknown type"}</div>
                      </div>
                    </div>
                    <div className="grid gap-3 text-sm">
                      <MetaRow label="Category" value={selectedDoc.category} />
                      <MetaRow label="Supplier" value={selectedDoc.supplier_name || "—"} />
                      <MetaRow label="Date" value={formatDate(selectedDoc.doc_date)} />
                      <MetaRow label="Size" value={formatBytes(selectedDoc.file_size)} />
                      <MetaRow label="Uploaded" value={new Date(selectedDoc.uploaded_at).toLocaleString()} />
                      <MetaRow label="Notes" value={selectedDoc.notes || "—"} />
                    </div>
                  </div>
                )}
              </aside>
            </div>
          ) : (
            // ── Catalog import view ──────────────────────────────────────────
            <div className="flex h-full flex-col gap-0 lg:flex-row">
              {/* Jobs list */}
              <div className="flex w-full shrink-0 flex-col border-b border-gray-800 lg:w-64 lg:border-b-0 lg:border-r">
                <div className="border-b border-gray-800 px-4 py-3 text-xs uppercase tracking-[0.25em] text-gray-500">Import Jobs</div>
                <div className="flex-1 overflow-auto p-3 space-y-2">
                  {jobsQuery.isLoading && <div className="text-sm text-gray-500 p-3">Loading...</div>}
                  {jobs.length === 0 && !jobsQuery.isLoading && (
                    <div className="text-sm text-gray-500 p-3">No import jobs yet.</div>
                  )}
                  {jobs.map(job => (
                    <button key={job.job_id} onClick={() => setActiveJobId(job.job_id)}
                      className={`w-full rounded-2xl border px-3 py-3 text-left transition ${
                        activeJobId === job.job_id ? "border-orange-500 bg-orange-500/10" : "border-gray-800 bg-gray-950 hover:border-gray-700"}`}>
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-sm font-medium text-gray-50">{job.file_name}</div>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase ${statusTone(job.status)}`}>{job.status}</span>
                      </div>
                      <div className="mt-1 text-xs text-gray-500">{formatDate(job.created_at)}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Right panel: import form + active job */}
              <div className="flex-1 space-y-6 overflow-auto px-4 py-6 sm:px-6">

                {/* Issuu scraper */}
                <div className="rounded-3xl border border-gray-800 bg-gray-900 p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <Globe className="h-4 w-4 text-orange-400" />
                    <div className="text-sm font-semibold text-gray-100">Import from Issuu</div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-[1fr_140px_100px]">
                    <div>
                      <div className="mb-1.5 text-xs uppercase tracking-[0.2em] text-gray-500">Issuu URL or CDN ID</div>
                      <input value={issuuUrl} onChange={e => setIssuuUrl(e.target.value)}
                        placeholder="https://issuu.com/cloudsent/docs/..."
                        className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
                    </div>
                    <div>
                      <div className="mb-1.5 text-xs uppercase tracking-[0.2em] text-gray-500">Brand Slug</div>
                      <input value={issuuSlug} onChange={e => setIssuuSlug(e.target.value)}
                        placeholder="jakes"
                        className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
                    </div>
                    <div>
                      <div className="mb-1.5 text-xs uppercase tracking-[0.2em] text-gray-500">Year</div>
                      <input value={issuuYear} onChange={e => setIssuuYear(e.target.value)}
                        placeholder="2026"
                        className="w-full rounded-2xl border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-3">
                    <button onClick={() => issuuImportMutation.mutate()}
                      disabled={!issuuUrl.trim() || issuuImportMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700 transition">
                      {issuuImportMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Globe className="h-4 w-4" />}
                      Scrape Catalog
                    </button>
                    {issuuImportMutation.isError && (
                      <div className="flex items-center gap-1 text-sm text-red-300">
                        <AlertCircle className="h-4 w-4" /> Failed — check URL
                      </div>
                    )}
                    {issuuImportMutation.isSuccess && (
                      <div className="text-sm text-emerald-300">Queued — see job list</div>
                    )}
                  </div>
                  <p className="mt-3 text-xs text-gray-500">
                    Paste an Issuu catalog URL or CDN ID. The system will fetch the accessibility text layer (no OCR needed), extract products by section, and load them into the database automatically.
                  </p>
                </div>

                {/* Active job detail */}
                {activeJobId && activeJob && (
                  <div className="space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Job #{activeJobId}</div>
                        <div className="mt-1 text-lg font-semibold text-gray-50">{activeJob.file_name}</div>
                      </div>
                      <span className={`rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-wider ${statusTone(jobStatus)}`}>
                        {jobStatus}
                      </span>
                    </div>

                    {(jobStatus === "pending" || jobStatus === "running") && (
                      <div className="rounded-3xl border border-blue-500/30 bg-blue-500/10 p-5 flex items-center gap-3">
                        <Loader2 className="h-5 w-5 animate-spin text-blue-300" />
                        <div className="text-sm text-blue-200">Processing catalog — this may take a minute…</div>
                      </div>
                    )}

                    {activeJob.error_message && (
                      <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-start gap-2">
                        <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />{activeJob.error_message}
                      </div>
                    )}

                    {jobStatus === "done" && (
                      <div className="rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-5">
                        <div className="text-lg font-semibold text-emerald-100">Import complete</div>
                        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
                          {Object.entries(activeJob.row_counts ?? {}).map(([k, v]) => (
                            <div key={k} className="rounded-2xl border border-white/10 bg-white/5 p-3">
                              <div className="text-xs uppercase tracking-[0.2em] text-white/50">{k}</div>
                              <div className="mt-1 text-xl font-semibold text-white">{v}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {jobStatus === "review" && (
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <div className="text-sm text-gray-400">{pendingRows.length} rows need review</div>
                          <button onClick={() => commitMutation.mutate()} disabled={commitMutation.isPending}
                            className="rounded-2xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-400 disabled:bg-gray-700 transition">
                            {commitMutation.isPending ? "Committing…" : "Commit Approved Rows"}
                          </button>
                        </div>

                        {pendingRows.map(row => {
                          const d = drafts[row.id] ?? {} as RowDraft;
                          const img = row.raw_data?.page_image_path ? `${apiBase}/v1/media/${row.raw_data.page_image_path}` : "";
                          return (
                            <div key={row.id} className="grid gap-4 rounded-2xl border border-gray-800 bg-gray-900 p-4 lg:grid-cols-[280px_1fr]">
                              <div className="overflow-hidden rounded-xl border border-gray-800 bg-gray-950 flex items-center justify-center min-h-[180px]">
                                {img ? <img src={img} alt="" className="w-full object-cover" /> : <span className="text-sm text-gray-600">No preview</span>}
                              </div>
                              <div className="space-y-3">
                                <div className="text-xs uppercase tracking-[0.2em] text-gray-500">Row {row.row_index + 1}</div>
                                <div className="grid gap-3 md:grid-cols-2">
                                  {(["name","item_code","brand","price","shot_count","category"] as (keyof RowDraft)[]).map(k => (
                                    <label key={k} className="block">
                                      <div className="mb-1 text-xs uppercase tracking-[0.2em] text-gray-500">{k.replace("_"," ")}</div>
                                      <input value={d[k] ?? ""} onChange={e => updateDraft(row.id, k, e.target.value)}
                                        className="w-full rounded-xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500" />
                                    </label>
                                  ))}
                                </div>
                                <label className="block">
                                  <div className="mb-1 text-xs uppercase tracking-[0.2em] text-gray-500">description</div>
                                  <textarea rows={3} value={d.description ?? ""} onChange={e => updateDraft(row.id, "description", e.target.value)}
                                    className="w-full rounded-xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500 resize-y" />
                                </label>
                                <div className="flex gap-2">
                                  <button onClick={() => rowMutation.mutate({ row, status: "approved" })} disabled={rowMutation.isPending}
                                    className="rounded-xl bg-emerald-500 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-400 disabled:bg-gray-700">Approve</button>
                                  <button onClick={() => rowMutation.mutate({ row, status: "rejected" })} disabled={rowMutation.isPending}
                                    className="rounded-xl bg-red-500 px-3 py-2 text-sm font-semibold text-white hover:bg-red-400 disabled:bg-gray-700">Reject</button>
                                  <button onClick={() => rowMutation.mutate({ row, status: "skipped" })} disabled={rowMutation.isPending}
                                    className="rounded-xl border border-gray-700 px-3 py-2 text-sm text-gray-300 hover:bg-gray-800">Skip</button>
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {!activeJobId && (
                  <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-10 text-center">
                    <PackageSearch className="mx-auto h-10 w-10 text-gray-600 mb-3" />
                    <div className="text-sm text-gray-400">Select a job from the left or start a new import above.</div>
                  </div>
                )}
              </div>
            </div>
          )}
        </main>
      </div>

      {/* Upload document modal */}
      {uploadOpen && (
        <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl sm:max-h-[90vh] sm:max-w-[42rem]">
            <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
              <div className="text-lg font-semibold text-gray-50">Upload Document</div>
              <button onClick={closeUploadModal} className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-400 hover:text-gray-100">
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="max-h-[calc(100vh-7rem)] space-y-5 overflow-auto p-4 sm:max-h-[calc(90vh-81px)] sm:p-5">
              <div onDragEnter={() => setDragActive(true)} onDragLeave={() => setDragActive(false)}
                onDragOver={e => e.preventDefault()} onDrop={onDropDoc}
                className={`rounded-3xl border border-dashed p-6 transition ${dragActive ? "border-orange-500 bg-orange-500/10" : "border-gray-800 bg-gray-950"}`}>
                <div className="flex flex-col items-center gap-3 text-center">
                  <Upload className="h-8 w-8 text-orange-300" />
                  <div className="text-sm text-gray-300">Drag & drop or choose a file</div>
                  <label className="cursor-pointer rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 transition">
                    Choose File
                    <input ref={fileInputRef} type="file" className="hidden" onChange={e => pickFile(e.target.files?.[0] ?? null)} />
                  </label>
                  {uploadFile && <div className="text-xs text-gray-500">{uploadFile.name}</div>}
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {[
                  { label: "Name", value: uploadName, set: setUploadName, placeholder: "Document name" },
                  { label: "Supplier", value: uploadSupplier, set: setUploadSupplier, placeholder: "Supplier name" },
                ].map(({ label, value, set, placeholder }) => (
                  <label key={label} className="block">
                    <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">{label}</div>
                    <input value={value} onChange={e => set(e.target.value)} placeholder={placeholder}
                      className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
                  </label>
                ))}
                <label className="block">
                  <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Category</div>
                  <select value={uploadCategory} onChange={e => setUploadCategory(e.target.value)}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500">
                    {DOC_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
                <label className="block">
                  <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Document Date</div>
                  <input type="date" value={uploadDate} onChange={e => setUploadDate(e.target.value)}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
                </label>
              </div>
              <label className="block">
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">Notes</div>
                <textarea rows={3} value={uploadNotes} onChange={e => setUploadNotes(e.target.value)}
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500" />
              </label>
              <div className="flex justify-end gap-3">
                <button onClick={closeUploadModal}
                  className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-2.5 text-sm text-gray-300 hover:border-gray-700">Cancel</button>
                <button onClick={() => uploadDocMutation.mutate()} disabled={!uploadFile || uploadDocMutation.isPending}
                  className="rounded-2xl bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-orange-400 disabled:bg-gray-700 transition">
                  {uploadDocMutation.isPending ? "Uploading…" : "Upload"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Small components ─────────────────────────────────────────────────────────

function SidebarBtn({ active, onClick, label, count, icon }: { active: boolean; onClick: () => void; label: string; count: number; icon?: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={`flex w-full items-center justify-between rounded-2xl border px-3 py-2.5 text-sm transition ${
        active ? "border-orange-500 bg-orange-500/10 text-orange-100" : "border-gray-800 bg-gray-950 text-gray-300 hover:border-gray-700"}`}>
      <span className="flex items-center gap-2">{icon}{label}</span>
      <span className="text-xs text-gray-500">{count}</span>
    </button>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-gray-800 bg-gray-900 px-3 py-2.5">
      <div className="text-[11px] uppercase tracking-[0.2em] text-gray-500">{label}</div>
      <div className="mt-1 text-sm text-gray-100">{value}</div>
    </div>
  );
}

function LoadingCard({ text }: { text: string }) {
  return <div className="rounded-3xl border border-gray-800 bg-gray-900 p-8 text-sm text-gray-400">{text}</div>;
}

function EmptyCard({ text }: { text: string }) {
  return <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-950 p-8 text-center text-sm text-gray-500">{text}</div>;
}
