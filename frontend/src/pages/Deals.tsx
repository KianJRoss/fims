import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, X } from "lucide-react";

import { api } from "../api/client";

type DealCondition = {
  id: number;
  condition_type: string;
  product_id: string | null;
  category_id: number | null;
  quantity: number | null;
  min_amount: number | null;
};

type DealReward = {
  id: number;
  reward_type: string;
  product_id: string | null;
  category_id: number | null;
  percent_off: number | null;
  flat_off: number | null;
  quantity: number;
};

type DealRecord = {
  id: number;
  name: string;
  deal_type: string;
  priority: number;
  is_active: boolean;
  is_stackable: boolean;
  valid_from: string | null;
  valid_until: string | null;
  notes: string | null;
  conditions: DealCondition[];
  rewards: DealReward[];
};

type ConditionForm = {
  condition_type: string;
  quantity: string;
  min_amount: string;
  product_id: string;
  category_id: string;
};

type RewardForm = {
  reward_type: string;
  percent_off: string;
  flat_off: string;
  product_id: string;
  category_id: string;
  quantity: string;
};

type DealForm = {
  name: string;
  deal_type: string;
  priority: string;
  is_active: boolean;
  is_stackable: boolean;
  valid_from: string;
  valid_until: string;
  notes: string;
  conditions: ConditionForm[];
  rewards: RewardForm[];
};

const DEAL_TYPE_OPTIONS = ["BXGY", "BUNDLE", "PERCENT_OFF", "FLAT_AMOUNT", "CLEARANCE"];
const CONDITION_TYPE_OPTIONS = ["MIN_QUANTITY", "MIN_AMOUNT", "PRODUCT", "CATEGORY"];
const REWARD_TYPE_OPTIONS = ["PERCENT_OFF", "FLAT_OFF", "CHEAPEST_FREE", "FREE_ITEM"];

const EMPTY_CONDITION: ConditionForm = {
  condition_type: "MIN_QUANTITY",
  quantity: "",
  min_amount: "",
  product_id: "",
  category_id: "",
};

const EMPTY_REWARD: RewardForm = {
  reward_type: "PERCENT_OFF",
  percent_off: "",
  flat_off: "",
  product_id: "",
  category_id: "",
  quantity: "1",
};

const EMPTY_FORM: DealForm = {
  name: "",
  deal_type: "BXGY",
  priority: "0",
  is_active: true,
  is_stackable: false,
  valid_from: "",
  valid_until: "",
  notes: "",
  conditions: [],
  rewards: [],
};

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `$${value.toFixed(2)}`;
}

function formatDateTime(value: string | null) {
  if (!value) return "Always valid";
  return new Date(value).toLocaleString();
}

function conditionSummary(condition: DealCondition) {
  const type = condition.condition_type.toUpperCase();
  if (type === "MIN_QUANTITY") return `Min qty ${condition.quantity ?? 0}`;
  if (type === "MIN_AMOUNT") return `Min amount ${formatMoney(condition.min_amount)}`;
  if (type === "PRODUCT") return `Product ${condition.product_id || "any"}${condition.quantity ? ` x${condition.quantity}` : ""}`;
  if (type === "CATEGORY") return `Category ${condition.category_id ?? "any"}${condition.quantity ? ` x${condition.quantity}` : ""}`;
  return type;
}

function rewardSummary(reward: DealReward) {
  const type = reward.reward_type.toUpperCase();
  if (type === "PERCENT_OFF") {
    const percent = reward.percent_off ?? 0;
    return `${percent <= 1 ? percent * 100 : percent}% off`;
  }
  if (type === "FLAT_OFF") return `${formatMoney(reward.flat_off)} off`;
  if (type === "CHEAPEST_FREE") return `Cheapest ${reward.quantity || 1} free`;
  if (type === "FREE_ITEM") return `Free item ${reward.product_id || reward.category_id || "selected"}`;
  return type;
}

function toIso(value: string) {
  return value ? new Date(value).toISOString() : null;
}

function parseOptionalNumber(value: string) {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function serializeCondition(form: ConditionForm) {
  const payload: Record<string, unknown> = {
    condition_type: form.condition_type,
  };
  const quantity = parseOptionalNumber(form.quantity);
  const minAmount = parseOptionalNumber(form.min_amount);
  const productId = form.product_id.trim();
  const categoryId = parseOptionalNumber(form.category_id);
  if (quantity !== undefined) payload.quantity = quantity;
  if (minAmount !== undefined) payload.min_amount = minAmount;
  if (productId) payload.product_id = productId;
  if (categoryId !== undefined) payload.category_id = categoryId;
  return payload;
}

function serializeReward(form: RewardForm) {
  const payload: Record<string, unknown> = {
    reward_type: form.reward_type,
  };
  const percentOff = parseOptionalNumber(form.percent_off);
  const flatOff = parseOptionalNumber(form.flat_off);
  const productId = form.product_id.trim();
  const categoryId = parseOptionalNumber(form.category_id);
  const quantity = parseOptionalNumber(form.quantity);
  if (percentOff !== undefined) payload.percent_off = percentOff;
  if (flatOff !== undefined) payload.flat_off = flatOff;
  if (productId) payload.product_id = productId;
  if (categoryId !== undefined) payload.category_id = categoryId;
  if (quantity !== undefined) payload.quantity = quantity;
  return payload;
}

export default function Deals() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState<DealForm>(EMPTY_FORM);

  const dealsQuery = useQuery({
    queryKey: ["deals"],
    queryFn: async (): Promise<DealRecord[]> => {
      const { data } = await api.get("/v1/deals/");
      return data;
    },
  });

  const createMutation = useMutation({
    mutationFn: async (payload: unknown) => {
      const { data } = await api.post("/v1/deals/", payload);
      return data as DealRecord;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["deals"] });
      setModalOpen(false);
      setForm(EMPTY_FORM);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: async (dealId: number) => {
      const { data } = await api.post(`/v1/deals/${dealId}/toggle`);
      return data as DealRecord;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (dealId: number) => {
      await api.delete(`/v1/deals/${dealId}`);
      return dealId;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["deals"] });
    },
  });

  const dealCards = useMemo(() => dealsQuery.data ?? [], [dealsQuery.data]);

  function openModal() {
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
    setForm(EMPTY_FORM);
  }

  function addCondition() {
    setForm((current) => ({ ...current, conditions: [...current.conditions, { ...EMPTY_CONDITION }] }));
  }

  function addReward() {
    setForm((current) => ({ ...current, rewards: [...current.rewards, { ...EMPTY_REWARD }] }));
  }

  function updateCondition(index: number, patch: Partial<ConditionForm>) {
    setForm((current) => ({
      ...current,
      conditions: current.conditions.map((condition, currentIndex) =>
        currentIndex === index ? { ...condition, ...patch } : condition
      ),
    }));
  }

  function updateReward(index: number, patch: Partial<RewardForm>) {
    setForm((current) => ({
      ...current,
      rewards: current.rewards.map((reward, currentIndex) => (currentIndex === index ? { ...reward, ...patch } : reward)),
    }));
  }

  function removeCondition(index: number) {
    setForm((current) => ({ ...current, conditions: current.conditions.filter((_, currentIndex) => currentIndex !== index) }));
  }

  function removeReward(index: number) {
    setForm((current) => ({ ...current, rewards: current.rewards.filter((_, currentIndex) => currentIndex !== index) }));
  }

  function submitDeal() {
    createMutation.mutate({
      name: form.name.trim(),
      deal_type: form.deal_type,
      priority: Number(form.priority) || 0,
      is_active: form.is_active,
      is_stackable: form.is_stackable,
      valid_from: toIso(form.valid_from),
      valid_until: toIso(form.valid_until),
      notes: form.notes.trim() || null,
      conditions: form.conditions
        .filter((condition) => condition.condition_type.trim())
        .map((condition) => serializeCondition(condition)),
      rewards: form.rewards
        .filter((reward) => reward.reward_type.trim())
        .map((reward) => serializeReward(reward)),
    });
  }

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-end">
          <button
            onClick={openModal}
            className="inline-flex items-center gap-2 rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400"
          >
            <Plus className="h-4 w-4" />
            New Deal
          </button>
        </div>
      </div>

      <div className="space-y-4 px-4 py-6 sm:px-6">
        {dealCards.map((deal) => (
          <div key={deal.id} className="rounded-3xl border border-gray-800 bg-gray-900 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-2xl font-semibold text-gray-50">{deal.name}</h2>
                  <span className="rounded-full border border-orange-500/30 bg-orange-500/10 px-2.5 py-1 text-xs text-orange-200">
                    {deal.deal_type}
                  </span>
                  <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-xs text-gray-300">
                    Priority {deal.priority}
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs ${
                      deal.is_active
                        ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                        : "border border-gray-700 bg-gray-950 text-gray-400"
                    }`}
                  >
                    {deal.is_active ? "Active" : "Inactive"}
                  </span>
                  {deal.is_stackable && (
                    <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-xs text-cyan-200">
                      Stackable
                    </span>
                  )}
                </div>

                <div className="space-y-2 text-sm text-gray-300">
                  <div className="text-gray-400">
                    Valid: <span className="text-gray-100">{formatDateTime(deal.valid_from)}</span> to{" "}
                    <span className="text-gray-100">{formatDateTime(deal.valid_until)}</span>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {deal.conditions.length > 0 ? (
                      deal.conditions.map((condition) => (
                        <span
                          key={condition.id}
                          className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-xs text-gray-300"
                        >
                          {conditionSummary(condition)}
                        </span>
                      ))
                    ) : (
                      <span className="rounded-full border border-gray-700 bg-gray-950 px-2.5 py-1 text-xs text-gray-400">
                        No conditions
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {deal.rewards.length > 0 ? (
                      deal.rewards.map((reward) => (
                        <span
                          key={reward.id}
                          className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200"
                        >
                          {rewardSummary(reward)}
                        </span>
                      ))
                    ) : (
                      <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200">
                        No rewards
                      </span>
                    )}
                  </div>
                  {deal.notes && <p className="max-w-none text-sm text-gray-400 lg:max-w-4xl">{deal.notes}</p>}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => toggleMutation.mutate(deal.id)}
                  className={`rounded-2xl px-3 py-2 text-sm font-semibold transition ${
                    deal.is_active
                      ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/15"
                      : "border border-gray-700 bg-gray-950 text-gray-300 hover:border-gray-600"
                  }`}
                >
                  {deal.is_active ? "Disable" : "Enable"}
                </button>
                <button
                  onClick={() => {
                    if (window.confirm(`Delete deal "${deal.name}"?`)) {
                      deleteMutation.mutate(deal.id);
                    }
                  }}
                  className="rounded-2xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        ))}

        {!dealsQuery.isLoading && dealCards.length === 0 && (
          <div className="rounded-3xl border border-dashed border-gray-800 bg-gray-900 p-12 text-center text-sm text-gray-500">
            No deals defined yet.
          </div>
        )}
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-40 flex items-start justify-center bg-black/70 px-3 py-3 sm:items-center sm:px-4 sm:py-8">
          <div className="max-h-[calc(100vh-1.5rem)] w-full max-w-[calc(100vw-1rem)] overflow-hidden rounded-3xl border border-gray-800 bg-gray-900 shadow-2xl shadow-black/50 sm:max-h-[90vh] sm:max-w-[56rem]">
            <div className="flex items-center justify-between border-b border-gray-800 px-5 py-4">
              <div>
                <div className="text-xs uppercase tracking-[0.25em] text-gray-500">New Deal</div>
                <div className="mt-1 text-lg font-semibold text-gray-50">Create a promotion</div>
              </div>
              <button
                onClick={closeModal}
                className="rounded-xl border border-gray-800 bg-gray-950 p-2 text-gray-400 transition hover:text-gray-100"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[calc(100vh-8rem)] overflow-auto p-4 sm:max-h-[calc(90vh-81px)] sm:p-5">
              <div className="grid gap-4 md:grid-cols-2">
                <Field label="Name">
                  <input
                    value={form.name}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                  />
                </Field>
                <Field label="Deal Type">
                  <select
                    value={form.deal_type}
                    onChange={(event) => setForm((current) => ({ ...current, deal_type: event.target.value }))}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                  >
                    {DEAL_TYPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Priority">
                  <input
                    type="number"
                    value={form.priority}
                    onChange={(event) => setForm((current) => ({ ...current, priority: event.target.value }))}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                  />
                </Field>
                <Field label="Valid From">
                  <input
                    type="datetime-local"
                    value={form.valid_from}
                    onChange={(event) => setForm((current) => ({ ...current, valid_from: event.target.value }))}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                  />
                </Field>
                <Field label="Valid Until">
                  <input
                    type="datetime-local"
                    value={form.valid_until}
                    onChange={(event) => setForm((current) => ({ ...current, valid_until: event.target.value }))}
                    className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                  />
                </Field>
                <div className="flex items-end gap-3">
                  <label className="flex flex-1 items-center justify-between rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-200">
                    <span>Active</span>
                    <input
                      type="checkbox"
                      checked={form.is_active}
                      onChange={(event) => setForm((current) => ({ ...current, is_active: event.target.checked }))}
                      className="accent-orange-500"
                    />
                  </label>
                  <label className="flex flex-1 items-center justify-between rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-200">
                    <span>Stackable</span>
                    <input
                      type="checkbox"
                      checked={form.is_stackable}
                      onChange={(event) => setForm((current) => ({ ...current, is_stackable: event.target.checked }))}
                      className="accent-orange-500"
                    />
                  </label>
                </div>
              </div>

              <Field label="Notes" className="mt-4">
                <textarea
                  value={form.notes}
                  onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
                  rows={3}
                  className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2.5 text-sm text-gray-100 outline-none focus:border-orange-500"
                />
              </Field>

              <div className="mt-6 grid gap-6 lg:grid-cols-2">
                <section className="rounded-3xl border border-gray-800 bg-gray-950 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Conditions</div>
                      <div className="mt-1 text-sm text-gray-400">Add one or more trigger rules.</div>
                    </div>
                    <button
                      onClick={addCondition}
                      className="rounded-2xl bg-orange-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-400"
                    >
                      Add Condition
                    </button>
                  </div>

                  <div className="mt-4 space-y-3">
                    {form.conditions.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-900 px-3 py-4 text-sm text-gray-500">
                        No conditions added.
                      </div>
                    ) : (
                      form.conditions.map((condition, index) => (
                        <div key={index} className="rounded-2xl border border-gray-800 bg-gray-900 p-3">
                          <div className="flex items-center justify-between gap-3">
                            <select
                              value={condition.condition_type}
                              onChange={(event) =>
                                updateCondition(index, { condition_type: event.target.value })
                              }
                              className="rounded-xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                            >
                              {CONDITION_TYPE_OPTIONS.map((option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                            <button
                              onClick={() => removeCondition(index)}
                              className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <Field label="Quantity">
                              <input
                                value={condition.quantity}
                                onChange={(event) => updateCondition(index, { quantity: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Min Amount">
                              <input
                                value={condition.min_amount}
                                onChange={(event) => updateCondition(index, { min_amount: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Product ID">
                              <input
                                value={condition.product_id}
                                onChange={(event) => updateCondition(index, { product_id: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Category ID">
                              <input
                                value={condition.category_id}
                                onChange={(event) => updateCondition(index, { category_id: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>

                <section className="rounded-3xl border border-gray-800 bg-gray-950 p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-xs uppercase tracking-[0.25em] text-gray-500">Rewards</div>
                      <div className="mt-1 text-sm text-gray-400">Define the discount or free item.</div>
                    </div>
                    <button
                      onClick={addReward}
                      className="rounded-2xl bg-orange-500 px-3 py-2 text-sm font-semibold text-white transition hover:bg-orange-400"
                    >
                      Add Reward
                    </button>
                  </div>

                  <div className="mt-4 space-y-3">
                    {form.rewards.length === 0 ? (
                      <div className="rounded-2xl border border-dashed border-gray-800 bg-gray-900 px-3 py-4 text-sm text-gray-500">
                        No rewards added.
                      </div>
                    ) : (
                      form.rewards.map((reward, index) => (
                        <div key={index} className="rounded-2xl border border-gray-800 bg-gray-900 p-3">
                          <div className="flex items-center justify-between gap-3">
                            <select
                              value={reward.reward_type}
                              onChange={(event) => updateReward(index, { reward_type: event.target.value })}
                              className="rounded-xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                            >
                              {REWARD_TYPE_OPTIONS.map((option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                            <button
                              onClick={() => removeReward(index)}
                              className="rounded-xl border border-red-500/30 bg-red-500/5 p-2 text-red-200 transition hover:bg-red-500/10"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </div>
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <Field label="Percent Off">
                              <input
                                value={reward.percent_off}
                                onChange={(event) => updateReward(index, { percent_off: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Flat Off">
                              <input
                                value={reward.flat_off}
                                onChange={(event) => updateReward(index, { flat_off: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Product ID">
                              <input
                                value={reward.product_id}
                                onChange={(event) => updateReward(index, { product_id: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Category ID">
                              <input
                                value={reward.category_id}
                                onChange={(event) => updateReward(index, { category_id: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                            <Field label="Quantity">
                              <input
                                value={reward.quantity}
                                onChange={(event) => updateReward(index, { quantity: event.target.value })}
                                className="w-full rounded-2xl border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-100 outline-none focus:border-orange-500"
                              />
                            </Field>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </section>
              </div>

              <div className="mt-6 flex flex-col-reverse items-stretch gap-3 sm:flex-row sm:items-center sm:justify-end">
                <button
                  onClick={closeModal}
                  className="rounded-2xl border border-gray-800 bg-gray-950 px-4 py-3 text-sm text-gray-300 transition hover:border-gray-700 hover:text-gray-100"
                >
                  Cancel
                </button>
                <button
                  onClick={submitDeal}
                  disabled={createMutation.isPending}
                  className="rounded-2xl bg-orange-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-orange-400 disabled:cursor-not-allowed disabled:bg-gray-700"
                >
                  {createMutation.isPending ? "Saving..." : "Save Deal"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
  className = "",
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`block ${className}`}>
      <div className="mb-2 text-xs uppercase tracking-[0.2em] text-gray-500">{label}</div>
      {children}
    </label>
  );
}
