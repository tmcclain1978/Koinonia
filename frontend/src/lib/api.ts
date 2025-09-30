// frontend/src/lib/api.ts
import axios from "axios"

// Allow both dev and prod configs
const API_BASE = import.meta.env.VITE_API_BASE || ""
const API_PREFIX = import.meta.env.VITE_API_PREFIX || "/api"  // <- default to Flask "/api"

const api = axios.create({
  baseURL: API_BASE || window.location.origin, // same-origin by default
  withCredentials: true, // <-- send cookies
})

function getCookie(name: string) {
  return document.cookie
    .split("; ")
    .map(v => v.split("="))
    .find(([k]) => k === name)?.[1]
}

api.interceptors.request.use((config) => {
  if (["post","put","patch","delete"].includes((config.method || "").toLowerCase())) {
    const csrf = getCookie(import.meta.env.VITE_CSRF_COOKIE_NAME || "csrf_token")
    if (csrf) {
      (config.headers ||= {})
      config.headers["X-CSRF-Token"] = csrf
    }
  }
  return config
})

/* ------------------ AUTH ------------------ */

export async function authLogin(email: string, password: string) {
  const { data } = await api.post(`${API_PREFIX}/auth/login`, { email, password })
  return data
}
export async function authLogout() {
  const { data } = await api.post(`${API_PREFIX}/auth/logout`)
  return data
}
export async function authMe() {
  const { data } = await api.get(`${API_PREFIX}/auth/me`)
  return data as {
    id: number
    email: string
    role: "user" | "admin"
    trade_enabled: boolean
    can_trade_paper: boolean
    can_trade_live: boolean
  }
}

// --- add to frontend/src/lib/api.ts ---

export async function authRegister(
  email: string,
  password: string,
  inviteCode?: string
) {
  const { data } = await api.post(`${API_PREFIX}/auth/register`, {
    email,
    password,
    inviteCode, // optional
  })
  return data as { id: number; email: string; role?: "user" | "admin" }
}

/* ------------------ ANALYTICS ------------------ */

export async function getIVRank(symbol: string) {
  const { data } = await api.get(`${API_PREFIX}/analytics/ivrank`, { params: { symbol } })
  return data
}
export async function getOIHeatmap(symbol: string) {
  const { data } = await api.get(`${API_PREFIX}/analytics/oi-heatmap`, { params: { symbol } })
  return data
}

/* ------------------ ADVISOR / SUGGESTIONS ------------------ */

// This is the function Home.tsx imports. It calls your Flask endpoint /api/ai/propose.
export type SuggestionResponse = {
  symbol: string
  side?: string
  qty?: number
  confidence?: number
  features?: any
}
export async function fetchSuggestion(symbol: string, opts?: { period?: string; interval?: string }) {
  const body = {
    symbol,
    period: opts?.period || "1D",
    interval: opts?.interval || "1m",
  }
  const { data } = await api.post<SuggestionResponse>(`${API_PREFIX}/ai/propose`, body)
  return data
}

// If you also use a GET /suggestions in other code, keep this helper too:
export async function getSuggestion(
  symbol: string,
  params?: { expiry?: string; strike?: number; bias?: "call" | "put" }
) {
  const { data } = await api.get(`${API_PREFIX}/suggestions`, { params: { symbol, ...params } })
  return data
}

/* ------------------ NEWS (for News.tsx) ------------------ */

export async function getNews(symbol: string) {
  // align with your server's news route if different (e.g., `${API_PREFIX}/news`)
  const { data } = await api.get(`${API_PREFIX}/news`, { params: { symbol } })
  // Expect shape: { items: [...] }
  return data as { items: any[] }
}

/* ------------------ TRADING ------------------ */

export async function placeTrade(
  mode: "paper" | "live",
  suggestion: any,
  risk_usd = 300,
  contracts = 1
) {
  const { data } = await api.post(`${API_PREFIX}/trade/place`, { mode, suggestion, risk_usd, contracts })
  return data
}

/* ------------------ OPTIONAL: Backtest (if used) ------------------ */

export async function runBacktest(symbol: string) {
  const { data } = await api.get(`${API_PREFIX}/backtest`, { params: { symbol } })
  return data as { equity: number[]; labels: string[] }
}

export default api
