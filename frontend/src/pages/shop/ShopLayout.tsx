import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { Sparkles } from "lucide-react";

type ShopLayoutProps = {
  children: ReactNode;
};

const navLinkClass =
  "rounded-full px-4 py-2 text-sm font-medium transition-colors";

function linkClass(isActive: boolean) {
  return `${navLinkClass} ${isActive ? "bg-sky-500 text-white shadow-sm" : "text-slate-600 hover:bg-sky-50 hover:text-sky-700"}`;
}

export default function ShopLayout({ children }: ShopLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <header className="border-b border-slate-100 bg-white shadow-sm">
        <div className="mx-auto flex max-w-7xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
          <NavLink to="/shop" className="flex items-center gap-2">
            <Sparkles className="h-6 w-6 text-sky-600" />
            <span className="text-lg font-semibold tracking-tight text-slate-900">Bodigons Fireworks</span>
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

      <footer className="border-t border-slate-200 bg-slate-100">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-4 py-6 text-sm text-slate-600 sm:px-6 lg:px-8">
          <span className="font-semibold text-slate-900">Bodigons Fireworks</span>
          <span>Light up your celebration</span>
        </div>
      </footer>
    </div>
  );
}
