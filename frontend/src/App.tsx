import { Routes, Route, NavLink, useLocation } from "react-router-dom";
import { Tv2 } from "lucide-react";
import SalesScreen from "./pages/SalesScreen";
import ProductCatalog from "./pages/ProductCatalog";
import Pricing from "./pages/Pricing";
import Deals from "./pages/Deals";
import Reports from "./pages/Reports";
import Receipt from "./pages/Receipt";
import BarcodePrint from "./pages/BarcodePrint";
import VideoReview from "./pages/VideoReview";
import Documents from "./pages/Documents";
import VideoRemote from "./pages/VideoRemote";

const navItems = [
  { to: "/", label: "Sales" },
  { to: "/products", label: "Products" },
  { to: "/pricing", label: "Pricing" },
  { to: "/barcodes", label: "Barcodes" },
  { to: "/videos", label: "Videos" },
  { to: "/video-remote", label: "Video Remote", icon: Tv2 },
  { to: "/documents", label: "Documents" },
  { to: "/deals", label: "Deals" },
  { to: "/reports", label: "Reports" },
];

export default function App() {
  const location = useLocation();

  if (location.pathname.startsWith("/receipt/")) {
    return (
      <Routes>
        <Route path="/receipt/:token" element={<Receipt />} />
      </Routes>
    );
  }

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 font-mono">
      <nav className="w-48 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col gap-1 p-3">
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

      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<SalesScreen />} />
          <Route path="/receipt/:token" element={<Receipt />} />
          <Route path="/products" element={<ProductCatalog />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/barcodes" element={<BarcodePrint />} />
          <Route path="/videos" element={<VideoReview />} />
          <Route path="/video-remote" element={<VideoRemote />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/deals" element={<Deals />} />
          <Route path="/reports" element={<Reports />} />
        </Routes>
      </main>
    </div>
  );
}
