
import Navbar from '../components/Navbar'
import Hero from '../components/Hero'
import EventsTicker from '../components/EventsTicker'
import Committees from '../components/Committees'
import HowItWorks from '../components/HowItWorks'
import Footer from '../components/Footer'

export default function Home() {
  return (
    <main className="min-h-screen overflow-hidden bg-[#080B12] text-white">
      <Navbar />
      <Hero />
      <EventsTicker />
      <Committees />
      <HowItWorks />
      <Footer />
    </main>
  )
}
