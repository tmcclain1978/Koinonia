import React, { createContext, useContext, useEffect, useState } from "react"
import { authLogin, authLogout, authMe } from "../lib/api"

type User = { id: number; email: string; role: "user"|"admin"; trade_enabled: boolean; can_trade_paper: boolean; can_trade_live: boolean }
type Ctx = {
  user: User | null
  login: (email:string, password:string)=>Promise<void>
  logout: ()=>Promise<void>
}
const AuthContext = createContext<Ctx>({ user: null, login: async()=>{}, logout: async()=>{} })
export const useAuth = () => useContext(AuthContext)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User|null>(null)
  useEffect(() => { authMe().then(setUser).catch(()=>setUser(null)) }, [])
  async function login(email: string, password: string) {
    await authLogin(email, password)   // sets cookies
    const me = await authMe()
    setUser(me)
  }
  async function logout() {
    await authLogout()
    setUser(null)
  }
  return <AuthContext.Provider value={{ user, login, logout }}>{children}</AuthContext.Provider>
}
