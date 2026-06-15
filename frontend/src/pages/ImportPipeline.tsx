import { useEffect, useMemo, useState, type DragEvent, type Dispatch, type ReactNode, type SetStateAction } from "react";
import axios from "axios";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

type ImportJobResponse = {
  job_id: number;
  status: string;
  created_at?: string;
  completed_at?: string | null;
  error_message?: string | null;
  row_counts?: Record<string, number>;
};

type ImportRow = {
  id: number;
  job_id: number;
  row_index: number;
  raw_data: Record<string, any>;
  matched_product_id?: string | null;
  match_confidence?: number | null;
  match_method?: string | null;
  review_status: string;
  reviewed_at?: string | null;
  notes?: string | null;
};

type ImportRowsResponse = {
  items: ImportRow[];
  page: number;
  per_page: number;
  total: number;
};

type RowDraft = {
  name?: string | null;
  item_code?: string | null;
  brand?: string | null;
  price?: number | string | null;
  shot_count?: number | string | null;
  description?: string | null;
  category?: string | null;
  packing?: string | null;
};

const apiBase = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
const api = axios.create({ baseURL: apiBase });

function mediaUrl(path: string) {
  return `${apiBase}/v1/media/${path}`;
}

export default function ImportPipeline() {
  const queryClient = useQueryClient();
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, RowDraft>>({});
  const [queuedCommit, setQueuedCommit] = useState(false);

  const jobQuery = useQuery({
    queryKey: ["import-job", jobId],
    queryFn: async (): Promise<ImportJobResponse> => {
      if (jobId === null) {
        throw new Error("Missing job id");
      }
      const { data } = await api.get(`/v1/imports/${jobId}`);
      return data;
    },
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && status !== "done" && status !== "failed" ? 2000 : false;
    },
  });

  const rowsQuery = useQuery({
    queryKey: ["import-rows", jobId, "pending"],
    queryFn: async (): Promise<ImportRowsResponse> => {
      if (jobId === null) {
        throw new Error("Missing job id");
      }
      const { data } = await api.get(`/v1/imports/${jobId}/rows`, {
        params: { status: "pending", page: 1, per_page: 200 },
      });
      return data;
    },
    enabled: jobId !== null && jobQuery.data?.status === "review",
    refetchInterval: false,
  });

  useEffect(() => {
    if (!rowsQuery.data?.items) return;
    const next: Record<number, RowDraft> = {};
    for (const row of rowsQuery.data.items) {
      const raw = row.raw_data ?? {};
      next[row.id] = {
        name: raw.name ?? "",
        item_code: raw.item_code ?? "",
        brand: raw.brand ?? "",
        price: raw.price ?? "",
        shot_count: raw.shot_count ?? "",
        description: raw.description ?? "",
        category: raw.category ?? "",
        packing: raw.packing ?? "",
      };
    }
    setDrafts((current) => ({ ...current, ...next }));
  }, [rowsQuery.data]);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("pdf", file);
      const { data } = await api.post("/v1/imports/pdf", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (event) => {
          if (!event.total) return;
          setUploadProgress(Math.round((event.loaded / event.total) * 100));
        },
      });
      return data as { job_id: number; status: string };
    },
    onSuccess: (data) => {
      setJobId(data.job_id);
      setQueuedCommit(false);
      setUploadProgress(100);
      queryClient.invalidateQueries({ queryKey: ["import-job", data.job_id] });
    },
  });

  const rowMutation = useMutation({
    mutationFn: async (payload: { row: ImportRow; status: string }) => {
      const draft = drafts[payload.row.id] ?? {};
      const body = {
        name: draft.name,
        item_code: draft.item_code,
        brand: draft.brand,
        price:
          draft.price === "" || draft.price === null || draft.price === undefined
            ? null
            : Number(draft.price),
        shot_count:
          draft.shot_count === "" || draft.shot_count === null || draft.shot_count === undefined
            ? null
            : Number(draft.shot_count),
        description: draft.description,
        category: draft.category,
        packing: draft.packing,
        review_status: payload.status,
      };
      const { data } = await api.patch(`/v1/imports/${jobId}/rows/${payload.row.id}`, body);
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["import-job", jobId] });
      await queryClient.invalidateQueries({ queryKey: ["import-rows", jobId, "pending"] });
    },
  });

  const commitMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post(`/v1/imports/${jobId}/commit`);
      return data as { queued: number };
    },
    onSuccess: async () => {
      setQueuedCommit(true);
      await queryClient.invalidateQueries({ queryKey: ["import-job", jobId] });
    },
  });

  const pendingRows = rowsQuery.data?.items ?? [];
  const totalRows = jobQuery.data?.row_counts?.total ?? rowsQuery.data?.total ?? 0;
  const remainingRows = pendingRows.length;
  const jobStatus = jobQuery.data?.status ?? (uploadMutation.isPending ? "uploading" : "idle");

  const statusTone = useMemo(() => {
    if (jobStatus === "done") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
    if (jobStatus === "failed") return "bg-red-500/15 text-red-300 border-red-500/30";
    if (jobStatus === "review") return "bg-amber-500/15 text-amber-300 border-amber-500/30";
    return "bg-slate-500/15 text-slate-300 border-slate-500/30";
  }, [jobStatus]);

  const canCommit = jobStatus === "review";

  function startUpload(file: File | null) {
    if (!file || uploadMutation.isPending) return;
    setSelectedFile(file);
    setUploadProgress(0);
    uploadMutation.mutate(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files?.[0];
    if (file) startUpload(file);
  }

  const emptyState = !jobId && !uploadMutation.isPending;

  return (
    <div className="min-h-full bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.16),_transparent_30%),radial-gradient(circle_at_bottom_right,_rgba(14,165,233,0.12),_transparent_28%),linear-gradient(180deg,_#0f172a_0%,_#020617_100%)] text-slate-100">
      <div className="mx-auto max-w-7xl px-4 py-6 lg:px-8">
        <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Import Pipeline</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">PDF catalog import and review</h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-400">
              Upload a supplier catalog PDF, review extracted rows against page images, then commit approved rows into the product catalog.
            </p>
          </div>
          <div className={`rounded-xl border px-4 py-3 text-sm ${statusTone}`}>
            <div className="font-medium uppercase tracking-[0.25em] text-[11px]">{jobStatus}</div>
            <div className="mt-1 text-xs text-slate-300/80">
              {jobId ? `Job #${jobId}` : "No active job"}
            </div>
          </div>
        </div>

        <div
          onDragEnter={() => setDragActive(true)}
          onDragLeave={() => setDragActive(false)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
          className={`rounded-3xl border border-dashed px-6 py-8 shadow-2xl shadow-black/20 transition ${
            dragActive ? "border-amber-400 bg-amber-500/10" : "border-slate-700 bg-slate-900/70"
          }`}
        >
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <p className="text-sm font-medium text-slate-200">Drop a PDF catalog here</p>
              <p className="mt-1 text-sm text-slate-400">
                Or choose a file from disk. The upload is sent to <code className="rounded bg-slate-950 px-1.5 py-0.5 text-[11px] text-slate-200">/v1/imports/pdf</code>.
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <label className="inline-flex cursor-pointer items-center justify-center rounded-xl bg-orange-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-orange-400">
                Choose PDF
                <input
                  type="file"
                  accept="application/pdf"
                  className="hidden"
                  onChange={(event) => startUpload(event.target.files?.[0] ?? null)}
                />
              </label>
              {selectedFile && (
                <div className="rounded-xl border border-slate-700 bg-slate-950/70 px-4 py-2 text-sm text-slate-300">
                  {selectedFile.name}
                </div>
              )}
            </div>
          </div>

          {(uploadMutation.isPending || uploadProgress > 0) && (
            <div className="mt-6">
              <div className="mb-2 flex items-center justify-between text-xs uppercase tracking-[0.2em] text-slate-400">
                <span>Upload progress</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div className="h-full rounded-full bg-gradient-to-r from-orange-500 via-amber-400 to-cyan-400 transition-all" style={{ width: `${uploadProgress}%` }} />
              </div>
            </div>
          )}
        </div>

        {jobQuery.data?.error_message && (
          <div className="mt-6 rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {jobQuery.data.error_message}
          </div>
        )}

        {jobStatus === "done" && (
          <div className="mt-6 rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-6">
            <h2 className="text-xl font-semibold text-emerald-100">Import complete</h2>
            <p className="mt-2 text-sm text-emerald-100/80">
              The catalog import finished and all approved rows have been committed.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <Stat label="Total rows" value={String(totalRows)} />
              <Stat label="Remaining" value={String(remainingRows)} />
              <Stat label="Queued videos" value={queuedCommit ? "Requested" : "Ready"} />
            </div>
          </div>
        )}

        {jobStatus === "review" && (
          <div className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/70 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-white">Review queue</h2>
                <p className="mt-1 text-sm text-slate-400">
                  {remainingRows} of {totalRows} remaining
                </p>
              </div>
              <button
                disabled={!canCommit || commitMutation.isPending}
                onClick={() => commitMutation.mutate()}
                className="rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
              >
                {commitMutation.isPending ? "Queueing commit..." : "Commit approved rows"}
              </button>
            </div>

            {!remainingRows && (
              <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/60 p-5 text-sm text-slate-400">
                All pending rows have been reviewed. Commit the approved rows to finish the import.
              </div>
            )}

            <div className="mt-6 space-y-4">
              {pendingRows.map((row) => {
                const draft = drafts[row.id] ?? {};
                const pageImage = row.raw_data?.page_image_path ? mediaUrl(row.raw_data.page_image_path) : "";
                return (
                  <div key={row.id} className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 lg:grid-cols-[340px_minmax(0,1fr)]">
                    <div className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
                      {pageImage ? (
                        <img src={pageImage} alt={`Page ${row.raw_data?.page ?? row.row_index + 1}`} className="h-full w-full object-cover" />
                      ) : (
                        <div className="flex h-64 items-center justify-center text-sm text-slate-500">No page preview</div>
                      )}
                    </div>

                    <div className="space-y-4">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">Row {row.row_index + 1}</p>
                          <h3 className="mt-1 text-lg font-semibold text-white">
                            {draft.name || row.raw_data?.name || "Unnamed product"}
                          </h3>
                        </div>
                        <span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-200">
                          {row.raw_data?.confidence ?? 0}
                        </span>
                      </div>

                      <div className="grid gap-3 md:grid-cols-2">
                        <Field label="Name">
                          <input value={draft.name ?? ""} onChange={(event) => updateDraft(row.id, "name", event.target.value, setDrafts)} className={inputClass} />
                        </Field>
                        <Field label="Item Code">
                          <input value={draft.item_code ?? ""} onChange={(event) => updateDraft(row.id, "item_code", event.target.value, setDrafts)} className={inputClass} />
                        </Field>
                        <Field label="Brand">
                          <input value={draft.brand ?? ""} onChange={(event) => updateDraft(row.id, "brand", event.target.value, setDrafts)} className={inputClass} />
                        </Field>
                        <Field label="Price">
                          <input
                            type="number"
                            step="0.01"
                            value={draft.price ?? ""}
                            onChange={(event) => updateDraft(row.id, "price", event.target.value, setDrafts)}
                            className={inputClass}
                          />
                        </Field>
                        <Field label="Shot Count">
                          <input
                            type="number"
                            value={draft.shot_count ?? ""}
                            onChange={(event) => updateDraft(row.id, "shot_count", event.target.value, setDrafts)}
                            className={inputClass}
                          />
                        </Field>
                        <Field label="Category">
                          <input value={draft.category ?? ""} onChange={(event) => updateDraft(row.id, "category", event.target.value, setDrafts)} className={inputClass} />
                        </Field>
                      </div>

                      <Field label="Description">
                        <textarea
                          rows={4}
                          value={draft.description ?? ""}
                          onChange={(event) => updateDraft(row.id, "description", event.target.value, setDrafts)}
                          className={`${inputClass} min-h-28 resize-y`}
                        />
                      </Field>

                      <div className="flex flex-col gap-3 sm:flex-row">
                        <button
                          onClick={() => rowMutation.mutate({ row, status: "approved" })}
                          disabled={rowMutation.isPending}
                          className="rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => rowMutation.mutate({ row, status: "rejected" })}
                          disabled={rowMutation.isPending}
                          className="rounded-xl bg-rose-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-rose-400 disabled:cursor-not-allowed disabled:bg-slate-700"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => rowMutation.mutate({ row, status: "skipped" })}
                          disabled={rowMutation.isPending}
                          className="rounded-xl border border-slate-700 px-4 py-2 text-sm font-semibold text-slate-200 transition hover:border-slate-500 hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-500"
                        >
                          Skip
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {emptyState && (
          <div className="mt-6 rounded-3xl border border-slate-800 bg-slate-900/70 p-8 text-center">
            <h2 className="text-xl font-semibold text-white">Start an import</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-slate-400">
              Upload a fireworks catalog PDF to generate review rows and page previews.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-xs uppercase tracking-[0.25em] text-white/50">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 text-xs uppercase tracking-[0.2em] text-slate-500">{label}</div>
      {children}
    </label>
  );
}

const inputClass =
  "w-full rounded-xl border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-orange-500 focus:ring-1 focus:ring-orange-500";

function updateDraft(
  rowId: number,
  key: keyof RowDraft,
  value: string,
  setDrafts: Dispatch<SetStateAction<Record<number, RowDraft>>>
) {
  setDrafts((current) => ({
    ...current,
    [rowId]: {
      ...(current[rowId] ?? {}),
      [key]: value,
    },
  }));
}
