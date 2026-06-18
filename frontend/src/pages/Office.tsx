import { useState } from "react";
import { BarChart3, BookText, ReceiptText } from "lucide-react";

import Documents from "./Documents";
import Receipts from "./Receipts";
import Reports from "./Reports";

type View = "documents" | "receipts" | "reports";

const VIEW_TABS: { id: View; label: string; icon: typeof BookText }[] = [
  { id: "documents", label: "Documents", icon: BookText },
  { id: "receipts", label: "Receipts", icon: ReceiptText },
  { id: "reports", label: "Reports", icon: BarChart3 },
];

export default function Office() {
  const [view, setView] = useState<View>("documents");

  return (
    <div className="min-h-full bg-gray-950 text-gray-100">
      <div className="border-b border-gray-800 bg-gray-950/95 px-4 py-4 backdrop-blur sm:px-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-300/80">Office</div>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-gray-50">
              {view === "documents" ? "Documents" : view === "receipts" ? "Receipts" : "Reports"}
            </h1>
          </div>
          <div className="inline-flex items-center rounded-2xl border border-gray-800 bg-gray-900 p-1">
            {VIEW_TABS.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setView(tab.id)}
                  className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-semibold transition ${
                    view === tab.id ? "bg-orange-500 text-gray-950" : "text-gray-400 hover:text-gray-100"
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {view === "documents" && <Documents />}
      {view === "receipts" && <Receipts />}
      {view === "reports" && <Reports />}
    </div>
  );
}
