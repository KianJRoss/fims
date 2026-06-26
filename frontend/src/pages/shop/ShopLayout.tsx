import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { Sparkles } from "lucide-react";

type ShopLayoutProps = {
  children: ReactNode;
};

const navLinkClass =
  "rounded-full px-4 py-2 text-sm font-medium transition-colors";

function linkClass(isActive: boolean) {
  return `${navLinkClass} ${
    isActive
      ? "bg-sky-500 text-white shadow-lg shadow-sky-950/20"
      : "text-slate-200 hover:bg-white/10 hover:text-white"
  }`;
}

export default function ShopLayout({ children }: ShopLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-[linear-gradient(180deg,_#0f172a_0%,_#1f2937_35%,_#334155_68%,_#f8fafc_100%)] text-slate-100">
      <header className="border-b border-white/10 bg-slate-950/70 shadow-2xl shadow-slate-950/20 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <NavLink to="/shop" className="flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-sky-300" />
            <span className="text-lg font-semibold tracking-tight text-white">Bodigon Fireworks</span>
          </NavLink>

          <nav className="flex items-center gap-2 overflow-x-auto pb-1 lg:justify-end">
            <NavLink to="/shop" end className={({ isActive }) => linkClass(isActive)}>
              Home
            </NavLink>
            <NavLink to="/shop/products" className={({ isActive }) => linkClass(isActive)}>
              Products
            </NavLink>
            <NavLink to="/shop/map" className={({ isActive }) => linkClass(isActive)}>
              Find Us
            </NavLink>
          </nav>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-white/10 bg-slate-950/80">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-sm text-slate-300 sm:px-6 lg:px-8">
          <span className="font-semibold text-white">Bodigon Fireworks</span>
          <span>Light up your celebration</span>
        </div>
      </footer>
    </div>
  );
}
