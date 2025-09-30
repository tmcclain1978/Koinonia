import React, { useEffect, useState } from "react"
import { getNews } from "../lib/api"

export default function News() {
  const [symbol, setSymbol] = useState("AAPL")
  const [items, setItems] = useState<any[]>([])

  useEffect(()=>{ (async()=>{
    const out = await getNews(symbol)
    setItems(out.items || [])
  })()},[symbol])

  return (
    <div className="space-y-4">
      <div className="flex gap-2 items-center">
        <input value={symbol} onChange={e=>setSymbol(e.target.value.toUpperCase())} className="border rounded px-3 py-2"/>
      </div>
      <div className="grid gap-3">
        {items.map((n,i)=>(
          <a key={i} href={n.url} target="_blank" className="p-3 border rounded-xl bg-white shadow-sm block">
            <div className="text-sm text-slate-500">{new Date(n.published).toLocaleString()}</div>
            <div className="font-medium">{n.title}</div>
            <div className={`inline-block mt-1 px-2 py-0.5 rounded text-xs ${n.sentiment>0 ? "bg-green-100 text-green-700" : n.sentiment<0 ? "bg-red-100 text-red-700" : "bg-slate-100 text-slate-700"}`}>
              Sentiment: {n.sentiment}
            </div>
          </a>
        ))}
      </div>
    </div>
  )
}
