
import { Activity } from 'lucide-react'

const events = [
  'Security Council discussions on maritime security',
  'Global food security negotiations intensify',
  'New climate financing proposals emerge',
]

export default function EventsTicker() {
  return (
    <section className="events-ticker" id="events">
      <div className="ticker-status">
        <span className="status-dot" />
        <Activity size={15} />
        GLOBAL BRIEFING
      </div>
      <div className="ticker-items">
        {events.map((event) => (
          <span key={event} className="ticker-item">
            {event}
          </span>
        ))}
      </div>
      <span className="ticker-arrow">↗</span>
    </section>
  )
}
