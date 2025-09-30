import React from "react"

const PRESETS = ["AAPL","NVDA","MSFT","TSLA","AMD","META","AMZN","SPY"]

export default function TickerPicker({
  value, onChange, onSubmit
}: { value: string; onChange: (v:string)=>void; onSubmit: ()=>void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={value}
        onChange={(e)=>onChange(e.target.value.toUpperCase())}
        placeholder="Enter ticker (e.g., AAPL)"
        className="px-3 py-2 rounded-lg border bg-white shadow-sm focus:outline-none focus:ring w-48"
      />
      <button
        onClick={onSubmit}
        className="px-4 py-2 rounded-lg bg-black text-white shadow-sm hover:opacity-90"
      >
        Get Suggestion
      </button>
      <div className="flex gap-1">
        {PRESETS.map(t => (
          <button
            key={t}
            onClick={()=>onChange(t)}
            className={`px-2 py-1 rounded-md border text-sm ${value===t ? "bg-black text-white" : "bg-white"}`}
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  )
}
