import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail, Plus, RefreshCw, Save, Settings as SettingsIcon, Trash2 } from "lucide-react";

import { api } from "../api/client";

type EmailAccount = {
  id: number;
  host: string;
  port: number;
  email_address: string;
  boss_email_filter: string | null;
  keyword_filter: string;
  last_synced_at: string | null;
  is_active: boolean;
  created_at: string;
};

type EmailDocument = {
  id: number;
  name: string;
  category: string;
  file_path: string;
  file_size: number | null;
  uploaded_at: string;
};

type MonitoringConfig = {
  enabled: boolean;
  backend_type: "api_key" | "cli";
  provider: "anthropic" | "claude";
  has_api_key: boolean;
  last_test_status: "ok" | "error" | null;
  last_test_message: string | null;
};

type MonitoringDraft = {
  enabled: boolean;
  backendType: "api_key" | "cli";
  apiKey: string;
};

type AccountDraft = {
  host: string;
  port: string;
  email_address: string;
  password: string;
  boss_email_filter: string;
  keyword_filter: string;
  is_active: boolean;
};

const DEFAULT_KEYWORDS = "invoice,order,price list,catalog,fireworks,shipment";

const emptyDraft: AccountDraft = {
  host: "",
  port: "993",
  email_address: "",
  password: "",
  boss_email_filter: "",
  keyword_filter: DEFAULT_KEYWORDS,
  is_active: true,
};

function formatDateTime(value: string | null | undefined) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatBytes(value: number | null) {
  if (!value) return "-";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB"];
  let current = value / 1024;
  let index = 0;
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024;
    index += 1;
  }
  return `${current.toFixed(current >= 10 ? 0 : 1)} ${units[index]}`;
}

function draftFromAccount(account: EmailAccount | null): AccountDraft {
  if (!account) return emptyDraft;
  return {
    host: account.host,
    port: String(account.port),
    email_address: account.email_address,
    password: "",
    boss_email_filter: account.boss_email_filter ?? "",
    keyword_filter: account.keyword_filter || DEFAULT_KEYWORDS,
    is_active: account.is_active,
  };
}

export default function Settings() {
  const queryClient = useQueryClient();
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [draft, setDraft] = useState<AccountDraft>(emptyDraft);
  const [monitoringDraft, setMonitoringDraft] = useState<MonitoringDraft>({
    enabled: false,
    backendType: "api_key",
    apiKey: "",
  });
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  const accountsQuery = useQuery({
    queryKey: ["email-accounts"],
    queryFn: async (): Promise<EmailAccount[]> => {
      const { data } = await api.get("/v1/email-accounts/");
      return data;
    },
  });

  const accounts = accountsQuery.data ?? [];
  const selectedAccount = useMemo(
    () => accounts.find((account) => account.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId]
  );

  const logQuery = useQuery({
    queryKey: ["email-accounts", selectedAccountId, "sync-log"],
    queryFn: async (): Promise<EmailDocument[]> => {
      const { data } = await api.get(`/v1/email-accounts/${selectedAccountId}/sync-log`);
      return data;
    },
    enabled: selectedAccountId !== null,
  });

  const monitoringQuery = useQuery({
    queryKey: ["ai-monitoring-config"],
    queryFn: async (): Promise<MonitoringConfig> => {
      const { data } = await api.get("/v1/monitoring/config");
      return data;
    },
  });

  useEffect(() => {
    if (selectedAccountId === null && accounts.length > 0) {
      setSelectedAccountId(accounts[0].id);
    }
  }, [accounts, selectedAccountId]);

  useEffect(() => {
    setDraft(draftFromAccount(selectedAccount));
  }, [selectedAccount]);

  useEffect(() => {
    if (!monitoringQuery.data) return;
    setMonitoringDraft((current) => ({
      ...current,
      enabled: monitoringQuery.data.enabled,
      backendType: monitoringQuery.data.backend_type,
    }));
  }, [monitoringQuery.data?.backend_type, monitoringQuery.data?.enabled]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        host: draft.host.trim(),
        port: Number(draft.port || 993),
        email_address: draft.email_address.trim(),
        boss_email_filter: draft.boss_email_filter.trim() || null,
        keyword_filter: draft.keyword_filter.trim() || DEFAULT_KEYWORDS,
        is_active: draft.is_active,
        ...(draft.password.trim() ? { password: draft.password } : {}),
      };

      if (selectedAccount) {
        const { data } = await api.put(`/v1/email-accounts/${selectedAccount.id}`, payload);
        return data as EmailAccount;
      }

      const { data } = await api.post("/v1/email-accounts/", {
        ...payload,
        password: draft.password,
      });
      return data as EmailAccount;
    },
    onSuccess: async (account) => {
      setSelectedAccountId(account.id);
      await queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/v1/email-accounts/${id}`);
      return id;
    },
    onSuccess: async (id) => {
      if (selectedAccountId === id) {
        setSelectedAccountId(null);
        setDraft(emptyDraft);
      }
      await queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
    },
  });

  const syncMutation = useMutation({
    mutationFn: async (id: number) => {
      const { data } = await api.post(`/v1/email-accounts/${id}/sync-now`);
      return data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["email-accounts"] });
      await queryClient.invalidateQueries({ queryKey: ["email-accounts", selectedAccountId, "sync-log"] });
    },
  });

  const monitoringSaveMutation = useMutation({
    mutationFn: async () => {
      const backendType = monitoringDraft.backendType;
      const provider = backendType === "api_key" ? "anthropic" : "claude";
      const payload: {
        enabled: boolean;
        backend_type: "api_key" | "cli";
        provider: "anthropic" | "claude";
        api_key?: string;
      } = {
        enabled: monitoringDraft.enabled,
        backend_type: backendType,
        provider,
      };
      if (monitoringDraft.apiKey.trim()) {
        payload.api_key = monitoringDraft.apiKey.trim();
      }
      const { data } = await api.put("/v1/monitoring/config", payload);
      return data as MonitoringConfig;
    },
    onSuccess: async (config) => {
      setMonitoringDraft((current) => ({
        ...current,
        enabled: config.enabled,
        backendType: config.backend_type,
        apiKey: "",
      }));
      await queryClient.invalidateQueries({ queryKey: ["ai-monitoring-config"] });
    },
  });

  const monitoringTestMutation = useMutation({
    mutationFn: async () => {
      const { data } = await api.post("/v1/monitoring/test");
      return data as { success: boolean; message: string };
    },
    onSuccess: (result) => {
      setTestResult(result);
      void queryClient.invalidateQueries({ queryKey: ["ai-monitoring-config"] });
    },
    onError: () => {
      setTestResult({
        success: false,
        message: "Unable to test the AI backend.",
      });
    },
  });

  const canSave =
    draft.host.trim() &&
    draft.email_address.trim() &&
    Number(draft.port) > 0 &&
    (selectedAccount !== null || draft.password.trim());

  function startNewAccount() {
    setSelectedAccountId(null);
    setDraft(emptyDraft);
  }

  return (
    <div className="min-h-full bg-gray-950 px-4 py-6 text-gray-100 sm:px-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="rounded-lg border border-gray-800 bg-gray-900 px-6 py-6">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.35em] text-orange-300/80">
                <SettingsIcon className="h-4 w-4" />
                Settings
              </div>
              <h1 className="mt-2 text-3xl font-semibold text-gray-50">Email inbox scraping</h1>
            </div>
            <button
              type="button"
              onClick={startNewAccount}
              className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-400"
            >
              <Plus className="h-4 w-4" />
              New Account
            </button>
          </div>
        </header>

        <div className="grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="rounded-lg border border-gray-800 bg-gray-900">
            <div className="border-b border-gray-800 px-4 py-3 text-xs uppercase tracking-[0.25em] text-gray-500">
              IMAP Accounts
            </div>
            <div className="space-y-2 p-3">
              {accountsQuery.isLoading ? (
                <div className="px-3 py-4 text-sm text-gray-400">Loading accounts...</div>
              ) : accounts.length === 0 ? (
                <div className="px-3 py-4 text-sm text-gray-500">No email accounts configured.</div>
              ) : (
                accounts.map((account) => (
                  <button
                    key={account.id}
                    type="button"
                    onClick={() => setSelectedAccountId(account.id)}
                    className={`w-full rounded-lg border px-3 py-3 text-left transition ${
                      selectedAccountId === account.id
                        ? "border-orange-500 bg-orange-500/10"
                        : "border-gray-800 bg-gray-950 hover:border-gray-700"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-gray-50">{account.email_address}</span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[10px] uppercase ${
                          account.is_active
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                            : "border-gray-700 bg-gray-800 text-gray-400"
                        }`}
                      >
                        {account.is_active ? "Active" : "Off"}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-xs text-gray-500">{account.host}:{account.port}</div>
                  </button>
                ))
              )}
            </div>
          </aside>

          <main className="flex flex-col gap-6">
            <section className="rounded-lg border border-gray-800 bg-gray-900">
              <div className="flex flex-col gap-3 border-b border-gray-800 px-5 py-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Account</div>
                  <div className="mt-1 text-sm text-gray-400">
                    Last sync: {formatDateTime(selectedAccount?.last_synced_at)}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedAccount ? (
                    <button
                      type="button"
                      onClick={() => syncMutation.mutate(selectedAccount.id)}
                      disabled={syncMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 transition hover:border-orange-500 disabled:cursor-not-allowed disabled:text-gray-500"
                    >
                      {syncMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                      Sync Now
                    </button>
                  ) : null}
                  {selectedAccount ? (
                    <button
                      type="button"
                      onClick={() => deleteMutation.mutate(selectedAccount.id)}
                      disabled={deleteMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200 transition hover:bg-red-500/20 disabled:cursor-not-allowed disabled:text-gray-500"
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="grid gap-4 p-5 md:grid-cols-2">
                <Field label="Host">
                  <input
                    value={draft.host}
                    onChange={(event) => setDraft((current) => ({ ...current, host: event.target.value }))}
                    placeholder="imap.gmail.com"
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <Field label="Port">
                  <input
                    type="number"
                    min={1}
                    max={65535}
                    value={draft.port}
                    onChange={(event) => setDraft((current) => ({ ...current, port: event.target.value }))}
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <Field label="Email">
                  <input
                    type="email"
                    value={draft.email_address}
                    onChange={(event) => setDraft((current) => ({ ...current, email_address: event.target.value }))}
                    placeholder="boss@example.com"
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <Field label={selectedAccount ? "New App Password" : "App Password"}>
                  <input
                    type="password"
                    value={draft.password}
                    onChange={(event) => setDraft((current) => ({ ...current, password: event.target.value }))}
                    placeholder={selectedAccount ? "Leave blank to keep current password" : ""}
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <Field label="Boss Sender Filter">
                  <input
                    value={draft.boss_email_filter}
                    onChange={(event) => setDraft((current) => ({ ...current, boss_email_filter: event.target.value }))}
                    placeholder="sender@example.com"
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <Field label="Keywords">
                  <input
                    value={draft.keyword_filter}
                    onChange={(event) => setDraft((current) => ({ ...current, keyword_filter: event.target.value }))}
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  />
                </Field>
                <label className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-950 px-3 py-3 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={draft.is_active}
                    onChange={(event) => setDraft((current) => ({ ...current, is_active: event.target.checked }))}
                    className="h-4 w-4 accent-orange-500"
                  />
                  Active scheduled sync
                </label>
              </div>

              <div className="flex items-center justify-between gap-3 border-t border-gray-800 px-5 py-4">
                <div className="text-sm text-gray-500">
                  {saveMutation.isError ? "Unable to save account." : syncMutation.isSuccess ? "Sync queued." : ""}
                </div>
                <button
                  type="button"
                  onClick={() => saveMutation.mutate()}
                  disabled={!canSave || saveMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                >
                  {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save Account
                </button>
              </div>
            </section>

            <section className="overflow-hidden rounded-lg border border-gray-800 bg-gray-900">
              <div className="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-4">
                <div className="flex items-center gap-2">
                  <Mail className="h-4 w-4 text-orange-300" />
                  <div>
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Email Imports</div>
                    <div className="mt-1 text-sm text-gray-400">Recent documents saved from inbox attachments</div>
                  </div>
                </div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">
                  {logQuery.data?.length ?? 0} rows
                </div>
              </div>

              {selectedAccountId === null ? (
                <div className="px-5 py-10 text-sm text-gray-500">Select or create an account to view imported documents.</div>
              ) : logQuery.isLoading ? (
                <div className="px-5 py-10 text-sm text-gray-400">Loading import log...</div>
              ) : logQuery.isError ? (
                <div className="px-5 py-10 text-sm text-red-200">Unable to load import log.</div>
              ) : logQuery.data?.length ? (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-800 text-sm">
                    <thead className="bg-gray-950 text-left text-xs uppercase tracking-[0.2em] text-gray-500">
                      <tr>
                        <th className="px-5 py-3 font-medium">Document</th>
                        <th className="px-5 py-3 font-medium">Category</th>
                        <th className="px-5 py-3 font-medium">Size</th>
                        <th className="px-5 py-3 font-medium">Imported</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-800">
                      {logQuery.data.map((document) => (
                        <tr key={document.id} className="bg-gray-900">
                          <td className="max-w-[24rem] truncate px-5 py-3 text-gray-100">{document.name}</td>
                          <td className="px-5 py-3 text-gray-300">{document.category}</td>
                          <td className="px-5 py-3 text-gray-400">{formatBytes(document.file_size)}</td>
                          <td className="px-5 py-3 text-gray-400">{formatDateTime(document.uploaded_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="px-5 py-10 text-sm text-gray-500">No email-imported documents yet.</div>
              )}
            </section>

            <section className="rounded-lg border border-gray-800 bg-gray-900">
              <div className="flex flex-col gap-3 border-b border-gray-800 px-5 py-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <SettingsIcon className="h-4 w-4 text-orange-300" />
                    <div className="text-xs uppercase tracking-[0.25em] text-gray-500">AI Monitoring</div>
                  </div>
                  <div className="mt-1 text-sm text-gray-400">
                    Optional LLM interpretation layered on top of the existing cron health checks
                  </div>
                </div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">
                  Last test: {monitoringQuery.data?.last_test_status ?? "-"}
                </div>
              </div>

              <div className="grid gap-4 p-5 md:grid-cols-2">
                <label className="flex items-center gap-3 rounded-lg border border-gray-800 bg-gray-950 px-3 py-3 text-sm text-gray-300">
                  <input
                    type="checkbox"
                    checked={monitoringDraft.enabled}
                    onChange={(event) =>
                      setMonitoringDraft((current) => ({ ...current, enabled: event.target.checked }))
                    }
                    className="h-4 w-4 accent-orange-500"
                  />
                  Enabled
                </label>

                <Field label="Backend Type">
                  <select
                    value={monitoringDraft.backendType}
                    onChange={(event) =>
                      setMonitoringDraft((current) => ({
                        ...current,
                        backendType: event.target.value as "api_key" | "cli",
                      }))
                    }
                    className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                  >
                    <option value="api_key">API Key</option>
                    <option value="cli">CLI Login</option>
                  </select>
                </Field>

                {monitoringDraft.backendType === "api_key" ? (
                  <>
                    <Field label="Provider">
                      <div className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-400">
                        Anthropic
                      </div>
                    </Field>
                    <Field label="Anthropic API Key">
                      <input
                        type="password"
                        value={monitoringDraft.apiKey}
                        onChange={(event) =>
                          setMonitoringDraft((current) => ({ ...current, apiKey: event.target.value }))
                        }
                        placeholder={monitoringQuery.data?.has_api_key ? "Saved API key" : "Enter Anthropic API key"}
                        className="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none transition focus:border-orange-500"
                      />
                    </Field>
                  </>
                ) : (
                  <div className="md:col-span-2 rounded-lg border border-gray-800 bg-gray-950 px-4 py-4 text-sm text-gray-400">
                    Run <span className="font-medium text-gray-200">claude login</span> once on the server so the
                    worker container can reuse that authenticated session, then test the connection below.
                  </div>
                )}
              </div>

              <div className="flex flex-col gap-3 border-t border-gray-800 px-5 py-4 md:flex-row md:items-center md:justify-between">
                <div className="text-sm text-gray-500">
                  {monitoringQuery.data?.last_test_message ?? "Save settings, then test the backend connection."}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => monitoringTestMutation.mutate()}
                    disabled={monitoringTestMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-100 transition hover:border-orange-500 disabled:cursor-not-allowed disabled:text-gray-500"
                  >
                    {monitoringTestMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                    Test Connection
                  </button>
                  <button
                    type="button"
                    onClick={() => monitoringSaveMutation.mutate()}
                    disabled={monitoringSaveMutation.isPending}
                    className="inline-flex items-center gap-2 rounded-lg bg-orange-500 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                  >
                    {monitoringSaveMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save
                  </button>
                </div>
              </div>
              {testResult ? (
                <div
                  className={`border-t border-gray-800 px-5 py-3 text-sm ${
                    testResult.success ? "text-emerald-300" : "text-red-200"
                  }`}
                >
                  {testResult.message}
                </div>
              ) : null}
            </section>
          </main>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">{label}</div>
      {children}
    </label>
  );
}
