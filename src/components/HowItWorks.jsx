
import { Globe2, BrainCircuit, MessagesSquare, ChartNoAxesCombined } from 'lucide-react'

const steps = [
  { icon: Globe2, number: '01', title: 'Choose a Committee', text: 'Step into an international forum and define your role.' },
  { icon: BrainCircuit, number: '02', title: 'Analyse & Strategise', text: 'Understand events, interests, and competing priorities.' },
  { icon: MessagesSquare, number: '03', title: 'Debate & Negotiate', text: 'Build alliances, challenge proposals, and find common ground.' },
  { icon: ChartNoAxesCombined, number: '04', title: 'See the Impact', text: 'Observe how diplomatic decisions change the simulation.' },
]

export default function HowItWorks() {
  return (
    <section className="how-section" id="how-it-works">
      <p className="eyebrow">FROM BRIEFING TO GLOBAL IMPACT</p>
      <h2>Every decision moves the world.</h2>
      <div className="steps-grid">
        {steps.map(({ icon: Icon, number, title, text }) => (
          <article className="step-card" key={number}>
            <Icon size={26} strokeWidth={1.4} />
            <span className="step-number">{number}</span>
            <h3>{title}</h3>
            <p>{text}</p>
          </article>
        ))}
      </div>
    </section>
  )
}
