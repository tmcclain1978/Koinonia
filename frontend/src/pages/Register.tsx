import React, { useState } from "react"
import { useNavigate, Link } from "react-router-dom"
import { authRegister } from "../lib/api"
import { useAuth } from "../auth/AuthContext"

export default function Register() {
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [inviteCode, setInviteCode] = useState("")  // NEW
  const [err, setErr] = useState<string | null>(null)
  const nav = useNavigate()
  const { login } = useAuth()

  async function submit() {
    setErr(null)
    try {
      const { access_token, role } = await authRegister(email, password, inviteCode) // pass code
      login(access_token, role)
      nav("/")
    } catch (e: any) {
      setErr(e?.response?.data?.detail || "Registration failed")
    }
  }

  return (
    <div className="max-w-md mx-auto space-y-4">
      <h1 className="text-xl font-semibold">Register</h1>
      {err && <div className="p-2 bg-red-50 border text-sm">{err}</div>}
      <input className="w-full p-2 border rounded" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} />
      <input className="w-full p-2 border rounded" placeholder="Password" type="password" value={password} onChange={e=>setPassword(e.target.value)} />
      <input className="w-full p-2 border rounded" placeholder="Access code (optional)" value={inviteCode} onChange={e=>setInviteCode(e.target.value)} /> {/* NEW */}
      <button onClick={submit} className="px-4 py-2 bg-black text-white rounded">Create Account</button>
      <div className="text-sm">Have an account? <Link to="/login" className="underline">Login</Link></div>
    </div>
  )
}
