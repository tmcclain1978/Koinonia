import React from "react"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

export default function PayoffChart({ suggestion }: { suggestion: any }) {
  if (!suggestion?.legs) return null
  // Stub: plot payoff vs spot around strikes
  const strikes = suggestion.legs.map((l:any)=>l.strike).filter(Boolean)
  const minK = Math.max(5, Math.min(...strikes) - 20)
  const maxK = Math.max(...strikes) + 20
  const data = []
  for (let s=minK; s<=maxK; s+=2) {
    // super-simplified payoff approximation at expiry for a vertical call spread
    let payoff = 0
    suggestion.legs.forEach((leg:any) => {
      const sign = leg.action === "BUY" ? 1 : -1
      if (leg.type === "CALL") payoff += sign * Math.max(0, s - leg.strike) * 100
      if (leg.type === "PUT")  payoff += sign * Math.max(0, leg.strike - s) * 100
    })
    // debit cost
    if (suggestion.debit) payoff -= suggestion.debit * 100
    data.push({ spot: s, payoff })
  }
  return (
    <div className="p-4 border rounded-2xl bg-white shadow-sm">
      <div className="font-semibold mb-2">Payoff at Expiry (approx)</div>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data}>
          <XAxis dataKey="spot" />
          <YAxis />
          <Tooltip />
          <Line type="monotone" dataKey="payoff" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
