import { useEffect, useState } from "react";
import { Routes, Route, Navigate, NavLink, useLocation } from "react-router-dom";
import {
  BookText,
  FileText,
  FolderOpen,
  Menu,
  Settings as SettingsIcon,
  SquareActivity,
  X,
} from "lucide-react";
import SalesScreen from "./pages/SalesScreen";
import ProductCatalog from "./pages/ProductCatalog";
import Receipt from "./pages/Receipt";
import VideoReview from "./pages/VideoReview";
import Office from "./pages/Office";
import Settings from "./pages/Settings";
import ShopLayout from "./pages/shop/ShopLayout";
import ShopHome from "./pages/shop/ShopHome";
import ShopProducts from "./pages/shop/ShopProducts";
import ShopProduct from "./pages/shop/ShopProduct";
import ShopMap from "./pages/shop/ShopMap";

const navItems = [
  { to: "/", label: "Sales", icon: SquareActivity },
  { to: "/products", label: "Products", icon: FolderOpen },
  { to: "/videos", label: "Videos", icon: FileText },
  { to: "/office", label: "Office", icon: BookText },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export default function App() {
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  if (location.pathname.startsWith("/receipt/")) {
    return (
      <Routes>
        <Route path="/receipt/:token" element={<Receipt />} />
      </Routes>
    );
  }

  if (location.pathname.startsWith("/shop")) {
    return (
      <ShopLayout>
        <Routes>
          <Route path="/shop" element={<ShopHome />} />
          <Route path="/shop/products" element={<ShopProducts />} />
          <Route path="/shop/product/:id" element={<ShopProduct />} />
          <Route path="/shop/map" element={<ShopMap />} />
        </Routes>
      </ShopLayout>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-gray-950 text-gray-100 font-sans lg:h-screen lg:flex-row">
      <header className="sticky top-0 z-40 border-b border-gray-800 bg-gray-950/95 px-4 py-3 backdrop-blur lg:hidden">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-[0.35em] text-orange-400">FIMS</div>
            <div className="mt-1 text-sm text-gray-400">Fireworks inventory management</div>
          </div>
          <button
            type="button"
            onClick={() => setMobileNavOpen(true)}
            className="inline-flex items-center justify-center rounded-2xl border border-gray-800 bg-gray-900 p-3 text-gray-100"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>
      </header>

      <nav className="hidden flex-shrink-0 flex-col gap-1 border-r border-gray-800 bg-gray-900 p-3 lg:w-48 lg:flex">
        <span className="text-orange-400 font-bold text-sm mb-3 uppercase tracking-widest">FIMS</span>
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? "bg-orange-500 text-white"
                  : "text-gray-400 hover:text-gray-100 hover:bg-gray-800"
              }`
            }
          >
            <span className="flex items-center gap-2">
              {Icon ? <Icon className="h-4 w-4" /> : null}
              <span>{label}</span>
            </span>
          </NavLink>
        ))}
      </nav>

      <main className="min-h-0 flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<SalesScreen />} />
          <Route path="/receipt/:token" element={<Receipt />} />
          <Route path="/inventory" element={<Navigate to="/products" replace />} />
          <Route path="/products" element={<ProductCatalog />} />
          <Route path="/pricing" element={<Navigate to="/products" replace />} />
          <Route path="/barcodes" element={<Navigate to="/products" replace />} />
          <Route path="/videos" element={<VideoReview />} />
          <Route path="/video-remote" element={<Navigate to="/videos" replace />} />
          <Route path="/office" element={<Office />} />
          <Route path="/documents" element={<Navigate to="/office" replace />} />
          <Route path="/suppliers" element={<Navigate to="/products" replace />} />
          <Route path="/deals" element={<Navigate to="/products" replace />} />
          <Route path="/reports" element={<Navigate to="/office" replace />} />
          <Route path="/receipts" element={<Navigate to="/office" replace />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>

      {mobileNavOpen ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/70"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation overlay"
          />
          <div className="absolute inset-y-0 left-0 w-[min(18rem,85vw)] border-r border-gray-800 bg-gray-900 shadow-2xl shadow-black/50">
            <div className="flex items-center justify-between border-b border-gray-800 px-4 py-4">
              <div>
                <div className="text-xs uppercase tracking-[0.35em] text-orange-400">FIMS</div>
                <div className="mt-1 text-sm text-gray-400">Navigation</div>
              </div>
              <button
                type="button"
                onClick={() => setMobileNavOpen(false)}
                className="rounded-2xl border border-gray-800 bg-gray-950 p-2 text-gray-300"
                aria-label="Close navigation"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex flex-col gap-1 p-3">
              {navItems.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === "/"}
                  onClick={() => setMobileNavOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center justify-between rounded-2xl px-4 py-3 text-sm transition ${
                      isActive
                        ? "bg-orange-500 text-white"
                        : "text-gray-300 hover:bg-gray-800 hover:text-gray-50"
                    }`
                  }
                >
                  <span className="flex items-center gap-3">
                    <Icon className="h-4 w-4" />
                    <span>{label}</span>
                  </span>
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
