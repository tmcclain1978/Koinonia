import React, { useEffect, useState } from "react"
import { runBacktest } from "../lib/api"
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"

export default function Backtest() {
  const [symbol, setSymbol] = useState("AAPL")
  const [data, setData] = useState<any>(null)

  async function go() {
    setData(await runBacktest(symbol))
  }
  useEffect(()=>{ go() },[]) // initial

  return (
    <div className="space-y-6">
      <div className="flex gap-2 items-center">
        <input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} className="border rounded px-3 py-2"/>
        <button onClick={go} className="px-3 py-2 rounded bg-black text-white">Run</button>
      </div>

      {data && (
        <div className="space-y-3">
          <div className="text-sm text-slate-600">
            Win rate: <b>{data.win_rate}</b> · Avg RR: <b>{data.avg_rr}</b> · Trades: <b>{data.trades}</b>
          </div>
          <div className="p-4 border rounded-2xl bg-white shadow-sm" style={{height:320}}>
            <div className="font-semibold mb-2">Equity Curve</div>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.equity_curve}>
                <XAxis dataKey="t" />
                <YAxis />
                <Tooltip />
                <Line type="monotone" dataKey="equity" dot={false}/>
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  )
}
