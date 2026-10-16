
import { ArrowUpRight, Shield, Globe2, Leaf, Landmark } from 'lucide-react'

const committees = [
  {
    acronym: 'UNGA',
    name: 'General Assembly',
    number: '01',
    icon: Globe2,
    description: 'Global cooperation and international policy.',
    tone: 'blue',
  },
  {
    acronym: 'UNSC',
    name: 'Security Council',
    number: '02',
    icon: Shield,
    description: 'Peace, security, and crisis response.',
    tone: 'gold',
  },
  {
    acronym: 'ECOSOC',
    name: 'Economic & Social Council',
    number: '03',
    icon: Landmark,
    description: 'Development, trade, and global welfare.',
    tone: 'slate',
  },
  {
    acronym: 'UNFCCC',
    name: 'Climate Change',
    number: '04',
    icon: Leaf,
    description: 'Climate action and environmental diplomacy.',
    tone: 'green',
  },
]

export default function Committees() {
  return (
    <section className="committees-section" id="committees">
      <div className="section-heading">
        <div>
          <p className="eyebrow">EXPLORE COMMITTEES</p>
          <h2>Take the Global Stage</h2>
        </div>
        <p className="section-intro">
          Join international forums where every decision
          creates new possibilities.
        </p>
        <a href="#simulation" className="text-link">
          Explore all <ArrowUpRight size={16} />
        </a>
      </div>

      <div className="committee-grid">
        {committees.map((item) => {
          const Icon = item.icon
          return (
            <a
              href="#simulation"
              key={item.acronym}
              className={`committee-card tone-${item.tone}`}
            >
              <div className="committee-card-top">
                <Icon size={25} strokeWidth={1.4} />
                <span>{item.number}</span>
              </div>
              <div className="committee-art">
                <span>{item.acronym}</span>
              </div>
              <h3>{item.name}</h3>
              <p>{item.description}</p>
              <span className="card-arrow">
                <ArrowUpRight size={17} />
              </span>
            </a>
          )
        })}
      </div>
    </section>
  )
}
