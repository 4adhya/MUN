
import { ArrowRight, Globe2, Menu, X } from 'lucide-react'
import { useState } from 'react'

export default function Navbar() {
  const [menuOpen, setMenuOpen] = useState(false)

  const links = [
    ['Home', '#home'],
    ['Simulation', '#simulation'],
    ['Committees', '#committees'],
    ['Resources', '#events'],
    ['About', '#how-it-works'],
  ]

  return (
    <header className="site-nav">
      <a href="#home" className="brand">
        <Globe2 size={24} strokeWidth={1.4} />
        <span>MUN</span>
      </a>

      <nav className={menuOpen ? 'nav-links nav-open' : 'nav-links'}>
        {links.map(([label, href], index) => (
          <a
            key={label}
            href={href}
            className={index === 0 ? 'nav-link active' : 'nav-link'}
            onClick={() => setMenuOpen(false)}
          >
            {label}
          </a>
        ))}
      </nav>

      <a className="button-primary nav-cta" href="#simulation">
        Enter Simulation <ArrowRight size={16} />
      </a>

      <button
        className="mobile-menu"
        aria-label="Toggle navigation"
        onClick={() => setMenuOpen(!menuOpen)}
      >
        {menuOpen ? <X /> : <Menu />}
      </button>
    </header>
  )
}
