import { useEffect, useRef, useState } from "react";

const ASSET_RE = /assets\/index-[A-Za-z0-9_-]+\.js/;
const POLL_INTERVAL_MS = 60_000;

/** Read the hash of the bundle currently executing in this tab. */
function currentBundleId(): string | null {
  const scripts = Array.from(
    document.querySelectorAll<HTMLScriptElement>('script[type="module"][src]'),
  );
  for (const script of scripts) {
    const match = script.getAttribute("src")?.match(ASSET_RE);
    if (match) return match[0];
  }
  return null;
}

/** Fetch the served index.html (cache-busted) and read the bundle hash it points at. */
async function deployedBundleId(): Promise<string | null> {
  try {
    const res = await fetch(`/index.html?ts=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return null;
    const html = await res.text();
    return html.match(ASSET_RE)?.[0] ?? null;
  } catch {
    return null;
  }
}

/**
 * Watches for a freshly deployed frontend build. An already-open POS tab keeps
 * running the old JS in memory until it is reloaded; this lets the UI surface a
 * reload prompt the moment a new build is live, instead of relying on someone
 * remembering Ctrl+Shift+R after every deploy.
 *
 * Returns true once the deployed bundle differs from the one this tab loaded.
 */
export function useBuildVersionWatcher(): boolean {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const baselineRef = useRef<string | null>(currentBundleId());

  useEffect(() => {
    let cancelled = false;

    async function check() {
      const deployed = await deployedBundleId();
      if (cancelled || !deployed) return;
      // Capture a baseline if the running tag wasn't readable for some reason.
      if (!baselineRef.current) {
        baselineRef.current = deployed;
        return;
      }
      if (deployed !== baselineRef.current) {
        setUpdateAvailable(true);
      }
    }

    const id = window.setInterval(check, POLL_INTERVAL_MS);
    // Also check when the tab regains focus -- a kiosk often sits idle.
    const onVisible = () => {
      if (document.visibilityState === "visible") check();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return updateAvailable;
}
