import React, { useEffect, useState } from "react"
import { useAuth } from "../auth/AuthContext"
import { getIVRank, getOIHeatmap, getSuggestion, placeTrade } from "../lib/api"

type GridCell = { expiry: string; strike: number; call_oi: number; put_oi: number }
type Bias = "call" | "put" | undefined
type Suggestion = any

export default function IV_OI() {
  const [symbol, setSymbol] = useState("AAPL")
  const [ivRank, setIvRank] = useState<number | null>(null)
  const [grid, setGrid] = useState<GridCell[]>([])
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const [sel, setSel] = useState<{ expiry: string; strike: number; bias?: Bias } | null>(null)
  const [sugg, setSugg] = useState<Suggestion | null>(null)
  const [suggLoading, setSuggLoading] = useState(false)
  const [suggErr, setSuggErr] = useState<string | null>(null)

  const { token } = useAuth()

  useEffect(() => {
    ;(async () => {
      try {
        setLoading(true); setErr(null); setSel(null); setSugg(null)
        const [iv, oi] = await Promise.all([getIVRank(symbol), getOIHeatmap(symbol)])
        setIvRank(typeof iv?.iv_rank === "number" ? iv.iv_rank : null)
        setGrid(Array.isArray(oi?.grid) ? oi.grid : [])
      } catch (e: any) {
        setErr(e?.response?.data?.detail || "Failed to load IV/OI data")
      } finally {
        setLoading(false)
      }
    })()
  }, [symbol])

  async function onPick(expiry: string, strike: number, bias?: Bias) {
    setSel({ expiry, strike, bias })
    setSugg(null); setSuggErr(null); setSuggLoading(true)
    try {
      const data = await getSuggestion(symbol, { expiry, strike, bias })
      setSugg(data)
    } catch (e: any) {
      setSuggErr(e?.response?.data?.detail || "Failed to fetch suggestion")
    } finally {
      setSuggLoading(false)
    }
  }

  async function onPaperTrade() {
    if (!sugg) return
    try {
      const resp = await placeTrade("paper", sugg, 300, 1)
      alert(`Trade ${resp.status}`)
    } catch (e: any) {
      alert(e?.response?.data?.detail || "Trade failed")
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <input
          className="border p-2 rounded w-40"
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          placeholder="Symbol (e.g. AAPL)"
        />
        {ivRank != null && (
          <div className="text-sm text-slate-600">
            IV Rank: <span className="font-semibold">{ivRank.toFixed(1)}</span>
          </div>
        )}
      </div>

      {loading && <div className="text-sm text-slate-600">Loading IV/OI…</div>}
      {err && <div className="p-2 bg-red-50 border text-sm">{err}</div>}

      {!loading && !err && (
        <HeatGrid grid={grid} onPick={onPick} />
      )}

      {/* Suggestion side panel */}
      {sel && (
        <div className="p-4 border rounded-lg space-y-3">
          <div className="text-sm text-slate-600">
            Selected: <span className="font-semibold">{symbol}</span>{" "}
            {sel.strike} exp {sel.expiry} {sel.bias ? `(${sel.bias})` : ""}
          </div>
          {suggLoading && <div className="text-sm text-slate-600">Building suggestion…</div>}
          {suggErr && <div className="p-2 bg-yellow-50 border text-sm">{suggErr}</div>}
          {sugg?.error && (
            <div className="p-2 bg-yellow-50 border text-sm">
              {sugg.error}: {sugg.detail}
            </div>
          )}
          {sugg?.legs && (
            <div className="space-y-2">
              <div className="font-semibold">{sugg.strategy}</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-slate-500 mb-1">Legs</div>
                  <pre className="text-xs bg-slate-50 p-2 rounded overflow-auto">{JSON.stringify(sugg.legs, null, 2)}</pre>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Meta</div>
                  <pre className="text-xs bg-slate-50 p-2 rounded overflow-auto">
                    {JSON.stringify({
                      debit: sugg.debit,
                      entry_rule: sugg.entry_rule,
                      exits: sugg.exits,
                      sizing: sugg.sizing,
                      spot: sugg?.context?.spot,
                      iv_rank: sugg?.context?.iv_rank
                    }, null, 2)}
                  </pre>
                </div>
              </div>
              <button
                onClick={onPaperTrade}
                disabled={!token}
                className={`px-3 py-2 rounded ${token ? "bg-black text-white" : "bg-slate-200 text-slate-500 cursor-not-allowed"}`}
                title={token ? "Submit paper order" : "Login required"}
              >
                {token ? "Place Paper Trade" : "Login to Trade"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ----------------------- HeatMap with color rules ----------------------- */

function HeatGrid({
  grid,
  onPick
}: {
  grid: GridCell[],
  onPick: (expiry: string, strike: number, bias?: Bias) => void
}) {
  // Tunables
  const SKEW_HIGH = 1.2     // >20% more calls than puts => green; <1/1.2 => red
  const TOP_DECILE = 0.90   // top 10% total OI => burgundy

  // normalize
  const rows = grid.map(g => ({
    expiry: g.expiry,
    strike: g.strike,
    call_oi: Number(g.call_oi || 0),
    put_oi: Number(g.put_oi || 0),
  }))

  const strikes = Array.from(new Set(rows.map(r => r.strike))).sort((a, b) => a - b)
  const expiries = Array.from(new Set(rows.map(r => r.expiry))).sort()

  const byKey = new Map<string, { call_oi: number; put_oi: number }>()
  rows.forEach(r => byKey.set(`${r.expiry}__${r.strike}`, { call_oi: r.call_oi, put_oi: r.put_oi }))

  // compute top decile threshold for total OI (for burgundy highlight)
  const totals = rows.map(r => r.call_oi + r.put_oi).sort((a, b) => a - b)
  const idx = Math.max(0, Math.floor(TOP_DECILE * (totals.length - 1)))
  const topCut = totals.length ? totals[idx] : Infinity

  const colorBurgundy = "#800020"
  const colorGreen = "#16a34a"
  const colorRed = "#ef4444"
  const colorGray = "#e5e7eb"
  const colorTextDark = "#111827"
  const colorTextLight = "#ffffff"

  function cellColor(callOI: number, putOI: number): string {
    const total = callOI + putOI
    if (total >= topCut && total > 0) return colorBurgundy              // high OI cluster
    const ratio = (callOI + 1) / (putOI + 1)
    if (ratio >= SKEW_HIGH) return colorGreen                           // bullish skew
    if (ratio <= 1 / SKEW_HIGH) return colorRed                         // bearish skew
    return colorGray                                                     // neutral
  }

  function textColor(bg: string): string {
    return (bg === colorBurgundy || bg === colorRed) ? colorTextLight : colorTextDark
  }

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex items-center gap-4 text-sm">
        <LegendSwatch label="Bullish skew" color={colorGreen} />
        <LegendSwatch label="Bearish skew" color={colorRed} />
        <LegendSwatch label="High OI cluster (top 10%)" color={colorBurgundy} />
      </div>

      {/* Grid */}
      <div className="overflow-auto border rounded-lg">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-50 sticky top-0">
            <tr>
              <th className="px-2 py-2 text-left">Expiry ⟶ / Strike ⤵</th>
              {expiries.map(ex => <th key={ex} className="px-2 py-2 whitespace-nowrap">{ex}</th>)}
            </tr>
          </thead>
          <tbody>
            {strikes.map(st => (
              <tr key={st} className="border-t">
                <td className="px-2 py-1 font-medium whitespace-nowrap">{st}</td>
                {expiries.map(ex => {
                  const v = byKey.get(`${ex}__${st}`) || { call_oi: 0, put_oi: 0 }
                  const bg = cellColor(v.call_oi, v.put_oi)
                  const fg = textColor(bg)
                  const ratio = (v.call_oi + 1) / (v.put_oi + 1)
                  const bias: Bias = ratio >= SKEW_HIGH ? "call" : (ratio <= 1 / SKEW_HIGH ? "put" : undefined)
                  const total = v.call_oi + v.put_oi
                  const intensity = total ? Math.max(0, Math.round(Math.log10(total) * 10)) : 0
                  const title = `Strike ${st} @ ${ex}\nCALL OI: ${v.call_oi.toLocaleString()} | PUT OI: ${v.put_oi.toLocaleString()}`

                  return (
                    <td key={ex} className="px-1 py-1 text-center">
                      <button
                        onClick={() => onPick(ex, st, bias)}
                        title={title}
                        className="w-16 h-6 rounded flex items-center justify-center"
                        style={{ background: bg, color: fg }}
                      >
                        {intensity}
                      </button>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LegendSwatch({ label, color }: { label: string; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <span style={{ background: color, display: "inline-block", width: 12, height: 12, borderRadius: 2 }} />
      <span>{label}</span>
    </div>
  )
}
