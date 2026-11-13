import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes the production bundle to ../static, which FastAPI serves.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../static", emptyOutDir: true },
  server: { proxy: { "/api": "http://localhost:8000" } },
});
