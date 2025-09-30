import React from "react"
import { createRoot } from "react-dom/client"

// Import your existing components
import IV_OI from "./IV_OI"          // default export or adjust to the actual export
import Backtest from "./Backtest"
import News from "./News"

// A tiny helper to read data-* from the container
function getConfig() {
  const root = document.getElementById("ai-advisor-root")
  const attr = (name: string) => root?.getAttribute(name) || ""

  return {
    symbol: attr("data-symbol") || "SPY",
    endpoints: {
      ivrank: attr("data-ivrank-endpoint"),
      oiheatmap: attr("data-oiheatmap-endpoint"),
      suggest: attr("data-suggest-endpoint"),
      backtest: attr("data-backtest-endpoint"),
      news: attr("data-news-endpoint"),
      placePaper: attr("data-place-paper-endpoint"),
      placeLive: attr("data-place-live-endpoint"),
    }
  }
}

// Optionally, wire up your axios/Fetch base here
function wireApiLayer(cfg: ReturnType<typeof getConfig>) {
  // Example: if your components use a local API module, you can set its base URLs here.
  // If they already call hardcoded /api/... routes, you can skip this.
  // e.g., Api.setEndpoints(cfg.endpoints)
}

function mount() {
  const cfg = getConfig()
  wireApiLayer(cfg)

  // Allow symbol form to re-render pages without a full reload (optional)
  const form = document.getElementById("ai-symbol-form") as HTMLFormElement | null
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault()
      const input = document.getElementById("ai-symbol") as HTMLInputElement
      const newSymbol = (input?.value || "SPY").trim().toUpperCase()
      const rootEl = document.getElementById("ai-advisor-root")
      if (rootEl) {
        rootEl.setAttribute("data-symbol", newSymbol)
        // Re-mount each widget to refetch with the new symbol
        renderWidgets()
      }
    })
  }

  renderWidgets()
}

function renderWidgets() {
  const cfg = getConfig()

  const ivoiEl = document.getElementById("iv-oi-root")
  if (ivoiEl) {
    const root = createRoot(ivoiEl)
    root.render(<IV_OI symbol={cfg.symbol} endpoints={cfg.endpoints} />)
  }

  const backtestEl = document.getElementById("backtest-root")
  if (backtestEl) {
    const root = createRoot(backtestEl)
    root.render(<Backtest symbol={cfg.symbol} endpoints={cfg.endpoints} />)
  }

  const newsEl = document.getElementById("news-root")
  if (newsEl) {
    const root = createRoot(newsEl)
    root.render(<News symbol={cfg.symbol} endpoints={cfg.endpoints} />)
  }
}

mount()
