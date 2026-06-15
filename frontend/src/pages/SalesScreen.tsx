import { useState, useRef, useEffect } from "react";
import axios from "axios";

interface CartItem {
  product_id: string;
  name: string;
  quantity: number;
  unit_price: number;
  override_price?: number;
}

export default function SalesScreen() {
  const [cart, setCart] = useState<CartItem[]>([]);
  const [barcode, setBarcode] = useState("");
  const [scanning, setScanning] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Keep focus on barcode input — USB scanner sends keyboard input here
  useEffect(() => {
    inputRef.current?.focus();
  });

  async function handleBarcodeScan(e: React.KeyboardEvent) {
    if (e.key !== "Enter" || !barcode.trim()) return;
    setScanning(true);
    try {
      const { data } = await axios.get(`/api/v1/products/lookup/barcode/${barcode.trim()}`);
      if (data.length === 1) {
        addToCart(data[0]);
      } else if (data.length > 1) {
        // Multiple products for this barcode — show picker (TODO)
        addToCart(data[0]);
      }
    } catch {
      // barcode not found — flash red (TODO)
    } finally {
      setBarcode("");
      setScanning(false);
    }
  }

  function addToCart(product: { id: string; name: string }) {
    setCart((prev) => {
      const existing = prev.findIndex((i) => i.product_id === product.id);
      if (existing >= 0) {
        return prev.map((item, idx) =>
          idx === existing ? { ...item, quantity: item.quantity + 1 } : item
        );
      }
      return [...prev, { product_id: product.id, name: product.name, quantity: 1, unit_price: 0 }];
    });
  }

  const total = cart.reduce(
    (sum, item) => sum + item.quantity * (item.override_price ?? item.unit_price),
    0
  );

  return (
    <div className="flex h-full">
      {/* Cart */}
      <div className="flex-1 flex flex-col p-4 gap-2">
        <div className="flex items-center gap-2 mb-2">
          <input
            ref={inputRef}
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            onKeyDown={handleBarcodeScan}
            placeholder="Scan barcode or type item number..."
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm focus:outline-none focus:border-orange-500"
          />
        </div>

        <div className="flex-1 overflow-auto border border-gray-800 rounded">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-gray-400 text-xs uppercase">
              <tr>
                <th className="px-3 py-2 text-left">Item</th>
                <th className="px-3 py-2 text-right w-16">Qty</th>
                <th className="px-3 py-2 text-right w-24">Price</th>
                <th className="px-3 py-2 text-right w-24">Total</th>
              </tr>
            </thead>
            <tbody>
              {cart.map((item) => (
                <tr key={item.product_id} className="border-t border-gray-800 hover:bg-gray-800/50">
                  <td className="px-3 py-2">{item.name}</td>
                  <td className="px-3 py-2 text-right">{item.quantity}</td>
                  <td className="px-3 py-2 text-right">${(item.override_price ?? item.unit_price).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">${(item.quantity * (item.override_price ?? item.unit_price)).toFixed(2)}</td>
                </tr>
              ))}
              {cart.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-8 text-center text-gray-600">Scan items to begin</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex justify-between items-center pt-2 border-t border-gray-800">
          <span className="text-gray-400 text-sm">{cart.reduce((s, i) => s + i.quantity, 0)} items</span>
          <span className="text-2xl font-bold text-orange-400">${total.toFixed(2)}</span>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setCart([])}
            className="flex-1 py-2 bg-gray-800 hover:bg-gray-700 rounded text-sm"
          >
            Clear
          </button>
          <button
            className="flex-1 py-2 bg-orange-500 hover:bg-orange-400 rounded text-sm font-bold"
            disabled={cart.length === 0}
          >
            Charge ${total.toFixed(2)}
          </button>
        </div>
      </div>
    </div>
  );
}
