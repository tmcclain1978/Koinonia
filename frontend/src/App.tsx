import React from "react"
import { BrowserRouter, Routes, Route, Navigate, Link } from "react-router-dom"
import { AuthProvider, useAuth } from "./auth/AuthContext"
import Home from "./pages/Home"
import Login from "./pages/Login"
import Register from "./pages/Register"
import IV_OI from "./pages/IV_OI"
import News from "./pages/News"
import Backtest from "./pages/Backtest"

function Guard({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function Nav() {
  const { logout, token } = useAuth()
  return (
    <nav className="flex items-center justify-between p-4 border-b bg-white">
      <div className="flex items-center gap-4">
        <Link to="/" className="font-semibold">AI Options Advisor</Link>
        {token && (
          <>
            <Link to="/iv-oi" className="text-sm text-slate-600 hover:underline">IV &amp; OI</Link>
            <Link to="/news" className="text-sm text-slate-600 hover:underline">News</Link>
            <Link to="/backtest" className="text-sm text-slate-600 hover:underline">Backtest</Link>
          </>
        )}
      </div>
      <div>
        {token ? (
          <button onClick={logout} className="px-3 py-1 rounded bg-black text-white">Logout</button>
        ) : (
          <Link to="/login" className="px-3 py-1 rounded border">Login</Link>
        )}
      </div>
    </nav>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Nav />
        <div className="max-w-6xl mx-auto p-6">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/" element={<Guard><Home /></Guard>} />
            <Route path="/iv-oi" element={<Guard><IV_OI /></Guard>} />
            <Route path="/news" element={<Guard><News /></Guard>} />
            <Route path="/backtest" element={<Guard><Backtest /></Guard>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </BrowserRouter>
    </AuthProvider>
  )
}
