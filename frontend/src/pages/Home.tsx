import React, { useState } from "react"
import TickerPicker from "../components/TickerPicker"
import SuggestionCard from "../components/SuggestionCard"
import { fetchSuggestion } from "../lib/api"
import PayoffChart from "../viz/PayoffChart"
import GreeksChart from "../viz/GreeksChart"

export default function Home() {
  const [ticker, setTicker] = useState("AAPL")
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setError(null); setLoading(true)
    try {
      const out = await fetchSuggestion(ticker)
      setData(out)
    } catch (e: any) {
      setError(e?.message || "Failed to fetch suggestion")
    } finally { setLoading(false) }
  }

  return (
    <div className="space-y-6">
      <div className="p-4 border rounded-2xl bg-white shadow-sm space-y-3">
        <TickerPicker value={ticker} onChange={setTicker} onSubmit={run} />
        <button onClick={run} disabled={loading} className="px-4 py-2 rounded-lg bg-black text-white">
          {loading ? "Fetching..." : "Suggest Trade"}
        </button>
        {error && <div className="p-3 rounded-lg bg-red-50 border text-sm">Error: {error}</div>}
      </div>

      <SuggestionCard data={data} />

      {data?.legs && (
        <div className="grid md:grid-cols-2 gap-6">
          <PayoffChart suggestion={data} />
          <GreeksChart suggestion={data} />
        </div>
      )}
    </div>
  )
}
