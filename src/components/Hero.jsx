
import { ArrowDown, ArrowRight } from 'lucide-react'
import InteractiveGlobe from './InteractiveGlobe'

export default function Hero() {
  return (
    <section className="hero-section" id="home">
      <div className="hero-copy">
        <p className="eyebrow">
          DIPLOMACY <span>·</span> STRATEGY <span>·</span> GLOBAL IMPACT
        </p>

        <h1>
          A More
          <br />
          Real World
          <br />
          to <span>Debate.</span>
        </h1>

        <p className="hero-description">
          An AI-powered Model United Nations simulation where
          global events evolve, your decisions matter, and
          diplomacy shapes the world.
        </p>

        <div className="hero-actions">
          <a className="button-primary" href="#simulation">
            Enter Simulation <ArrowRight size={17} />
          </a>
          <a className="button-secondary" href="#committees">
            Learn More <ArrowDown size={16} />
          </a>
        </div>

        <div className="hero-meta">
          <span className="status-dot" />
          A NEW PERSPECTIVE ON GLOBAL AFFAIRS
        </div>
      </div>

      <div className="hero-visual">
        <InteractiveGlobe />
      </div>
    </section>
  )
}
