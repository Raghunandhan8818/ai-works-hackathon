import LandingNav from '@/components/landing/LandingNav'
import Hero from '@/components/landing/Hero'
import StatsStrip from '@/components/landing/StatsStrip'
import HowItWorks from '@/components/landing/HowItWorks'
import Features from '@/components/landing/Features'
import GitHubBotPreview from '@/components/landing/GitHubBotPreview'
import EnterpriseSection from '@/components/landing/EnterpriseSection'
import LandingCTA from '@/components/landing/LandingCTA'
import LandingFooter from '@/components/landing/LandingFooter'

export default function LandingPage() {
  return (
    <div style={{ background: '#07090F' }}>
      <LandingNav />
      <Hero />
      <StatsStrip />
      <HowItWorks />
      <Features />
      <GitHubBotPreview />
      <EnterpriseSection />
      <LandingCTA />
      <LandingFooter />
    </div>
  )
}
