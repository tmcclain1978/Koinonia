import React from "react"

type Leg = {
  type: "CALL" | "PUT"
  action: "BUY" | "SELL"
  strike?: number
  expiry?: string
  qty?: number
  mid?: number
  greeks?: { delta?: number; theta?: number; vega?: number }
}

export default function SuggestionCard({ data }: { data: any }) {
  if (!data) return null
  if (data.error) return <div className="p-4 border rounded-lg bg-red-50">Error: {data.error}</div>
  if (data.skip || data.note) return <div className="p-4 border rounded-lg bg-yellow-50">Note: {data.skip || data.note}</div>

  return (
    <div className="p-4 border rounded-2xl bg-white shadow-sm space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">{data.ticker} — {data.strategy?.replaceAll("_"," ")}</h2>
        <div className="text-sm text-slate-600">RR: {data.risk_reward ?? "-"}</div>
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        <div className="space-y-2">
          <div className="font-medium">Trade</div>
          <ul className="text-sm space-y-1">
            {(data.legs || []).map((leg: Leg, i: number) => (
              <li key={i} className="p-2 rounded-lg bg-slate-50 border">
                <span className="font-semibold">{leg.action} {leg.type}</span>
                {leg.strike ? ` @ ${leg.strike}` : ""} {leg.expiry ? ` · ${leg.expiry}` : ""}
                {typeof leg.mid === "number" ? ` · mid ${leg.mid}` : ""}
                {leg.greeks?.delta !== undefined ? ` · Δ ${leg.greeks.delta}` : ""}
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-2">
          <div className="font-medium">Risk</div>
          <div className="text-sm p-2 rounded-lg bg-slate-50 border">
            Debit: {data.debit ?? "-"} · Max Profit: {data.max_profit ?? "-"}
          </div>
          <div className="font-medium">Exits</div>
          <div className="text-sm p-2 rounded-lg bg-slate-50 border">
            TP: {data.exits?.take_profit?.target_pct ?? "-"}% · SL: {data.exits?.stop_loss?.max_debit_pct ?? "-"}% · Time Exit: {data.exits?.time_exit?.days_before_expiry ?? "-"} days
          </div>
        </div>
      </div>

      <div className="space-y-1">
        <div className="font-medium">Entry Rule</div>
        <div className="text-sm p-2 rounded-lg bg-slate-50 border">{data.entry_rule ?? "-"}</div>
      </div>
    </div>
  )
}
