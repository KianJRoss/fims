import { useEffect } from "react";

const STREAM_BASE_URL = (import.meta.env.VITE_API_URL ?? "/api").replace(/\/$/, "");

type ScannerPayload = {
  barcode?: unknown;
  ts?: unknown;
};

export function useScannerStream(onBarcode: (barcode: string) => void) {
  useEffect(() => {
    if (typeof window.EventSource === "undefined") {
      return;
    }

    const source = new EventSource(`${STREAM_BASE_URL}/v1/scanner/stream`);

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as ScannerPayload;
        if (typeof payload.barcode === "string" && payload.barcode.trim()) {
          onBarcode(payload.barcode.trim());
        }
      } catch {
        // Ignore malformed scanner messages and keep the stream alive.
      }
    };

    return () => {
      source.close();
    };
  }, [onBarcode]);
}
