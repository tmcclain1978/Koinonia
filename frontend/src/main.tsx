// frontend/src/main.tsx or index.tsx
import { BrowserRouter, Routes, Route } from "react-router-dom"
import Home from "./pages/Home"
import IV_OI from "./pages/IV_OI"
import Backtest from "./pages/Backtest"
import News from "./pages/News"
import Login from "./pages/Login"
import Register from "./pages/Register"

export default function App() {
  return (
    <BrowserRouter basename="/dashboard/advisor">
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/iv-oi" element={<IV_OI />} />
        <Route path="/backtest" element={<Backtest />} />
        <Route path="/news" element={<News />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
      </Routes>
    </BrowserRouter>
  )
}
