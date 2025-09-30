import React from "react"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

export default function GreeksChart({ suggestion }: { suggestion: any }) {
  if (!suggestion?.legs) return null
  const legs = suggestion.legs.map((l:any, i:number) => ({
    name: `${l.action} ${l.type} ${l.strike || ""}`,
    delta: l.greeks?.delta ?? 0,
    theta: l.greeks?.theta ?? 0,
    vega: l.greeks?.vega ?? 0,
  }))
  return (
    <div className="p-4 border rounded-2xl bg-white shadow-sm">
      <div className="font-semibold mb-2">Greeks (per leg)</div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={legs}>
          <XAxis dataKey="name" hide />
          <YAxis />
          <Tooltip />
          <Bar dataKey="delta" />
          <Bar dataKey="theta" />
          <Bar dataKey="vega" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
