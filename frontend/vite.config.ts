import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // The API runs on :8000; proxying keeps the browser on one origin.
    proxy: { "/api": process.env.VITE_API_URL ?? "http://127.0.0.1:8000" },
  },
  test: { environment: "node" },
});
