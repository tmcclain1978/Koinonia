import React, { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import { authLogin } from "../lib/api"
import { useAuth } from "../auth/AuthContext"

export default function Login() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [err, setErr] = useState<string | null>(null)
  const nav = useNavigate()
  const { login } = useAuth()

  async function submit() {
    setErr(null)
    try {
      const { access_token, role } = await authLogin(email, password)
      login(access_token, role)
      nav("/")
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Login failed")
    }
  }

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="text-xl font-semibold">Login</h1>
      {err && <div className="p-2 bg-red-50 border text-sm">{err}</div>}
      <input className="w-full p-2 border rounded" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} />
      <input className="w-full p-2 border rounded" placeholder="Password" type="password" value={password} onChange={e=>setPassword(e.target.value)} />
      <button onClick={submit} className="px-4 py-2 bg-black text-white rounded">Login</button>
      <div className="text-sm">No account? <Link to="/register" className="underline">Register</Link></div>
    </div>
  )
}
