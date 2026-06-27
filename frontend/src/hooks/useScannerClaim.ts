import { useEffect } from "react";

import { api } from "../api/client";

const API_BASE = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");
// Renew well inside the server's 15s claim TTL so a single slow request never
// drops the claim, but quickly enough that a slept/closed client lets go fast.
const HEARTBEAT_MS = 6000;
const CLIENT_ID_KEY = "fims-scanner-client-id";

function getClientId(): string {
  let id = sessionStorage.getItem(CLIENT_ID_KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `c-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    sessionStorage.setItem(CLIENT_ID_KEY, id);
  }
  return id;
}

/**
 * Claim the shared barcode scanner for `target` while this page is open and
 * visible. Heartbeats keep the claim alive; backgrounding the tab, sleeping the
 * device, or unmounting releases it, so the scanner falls back to the Remote
 * (video) player automatically instead of staying stuck on this page.
 */
export function useScannerClaim(target: "sales" | "inventory") {
  useEffect(() => {
    const clientId = getClientId();

    const claim = () => {
      if (document.visibilityState !== "visible") return;
      void api.post("/v1/scanner/claim", { client_id: clientId, target }).catch(() => {});
    };

    const release = () => {
      // Best-effort during teardown/hide. sendBeacon survives page unload where
      // a normal fetch would be cancelled.
      const body = JSON.stringify({ client_id: clientId });
      if (typeof navigator !== "undefined" && navigator.sendBeacon) {
        navigator.sendBeacon(`${API_BASE}/v1/scanner/release`, new Blob([body], { type: "application/json" }));
      } else {
        void api.post("/v1/scanner/release", { client_id: clientId }).catch(() => {});
      }
    };

    claim();
    const interval = window.setInterval(claim, HEARTBEAT_MS);

    const onVisibility = () => {
      if (document.visibilityState === "visible") claim();
      else release();
    };

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", release);

    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", release);
      release();
    };
  }, [target]);
}
