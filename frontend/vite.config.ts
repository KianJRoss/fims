import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base:  /shop/,
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3000,
    hmr: {
      clientPort: 80,
    },
    watch: {
      usePolling: true,
      interval: 500,
    },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
