
import { Globe2, ArrowUpRight } from 'lucide-react'

export default function Footer() {
  return (
    <footer className="site-footer">
      <a href="#home" className="brand">
        <Globe2 size={22} strokeWidth={1.4} />
        <span>MUN</span>
      </a>
      <p>Made for a more informed world.</p>
      <a href="#home" className="footer-top">
        Back to top <ArrowUpRight size={15} />
      </a>
    </footer>
  )
}
