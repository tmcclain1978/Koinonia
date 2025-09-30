import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import path from "path"

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: path.resolve(__dirname, "../static"), // -> C:\AI Advisor\static
    emptyOutDir: false, // don't wipe the whole static folder
    rollupOptions: {
      input: {
        ai_advisor: path.resolve(__dirname, "src/pages/ai_advisor.tsx"),
      },
      output: {
        entryFileNames: "js/[name].bundle.js",
        chunkFileNames: "js/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash][extname]",
      },
    },
  },
})
