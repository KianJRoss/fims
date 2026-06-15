import { useEffect, useRef } from "react";

const STREAM_BASE_URL = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");

type ScannerPayload = {
  barcode?: unknown;
  ts?: unknown;
};

export function useScannerStream(onBarcode: (barcode: string) => void) {
  const onBarcodeRef = useRef(onBarcode);

  useEffect(() => {
    onBarcodeRef.current = onBarcode;
  }, [onBarcode]);

  useEffect(() => {
    if (typeof window.EventSource === "undefined") {
      return;
    }

    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryDelay = 1000;
    let destroyed = false;

    function connect() {
      if (destroyed) return;
      source = new EventSource(`${STREAM_BASE_URL}/v1/scanner/stream`);

      source.onmessage = (event) => {
        retryDelay = 1000;
        try {
          const payload = JSON.parse(event.data) as ScannerPayload;
          if (typeof payload.barcode === "string" && payload.barcode.trim()) {
            onBarcodeRef.current(payload.barcode.trim());
          }
        } catch {
          // ignore malformed messages
        }
      };

      source.onerror = () => {
        source?.close();
        source = null;
        if (!destroyed) {
          retryTimer = setTimeout(() => {
            retryDelay = Math.min(retryDelay * 2, 30000);
            connect();
          }, retryDelay);
        }
      };
    }

    connect();

    return () => {
      destroyed = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      source?.close();
    };
  }, []);
}
