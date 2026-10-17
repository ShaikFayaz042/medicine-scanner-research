import { useEffect, useState } from 'react'
import {
  ArrowRight, Camera, ChevronRight, Clock, Download, FileText, HeartPulse,
  Menu, Play, ScanBarcode, ScanLine, Settings, ShieldCheck, Smartphone, X, Zap,
} from 'lucide-react'

const APK_URL = (import.meta.env.VITE_ANDROID_APK_URL || '').trim()

const NAV = [
  ['Home', '#home'],
  ['Features', '#features'],
  ['How it works', '#how-it-works'],
  ['About', '#about'],
  ['FAQ', '#faq'],
]

const FEATURES = [
  { icon: ScanBarcode, title: 'Barcode scanning', text: 'Scan a medicine barcode to see the product information available for it.', tint: 'bg-sky-100 text-sky-700' },
  { icon: FileText, title: 'Label recognition', text: 'Point the camera at a label and MediCheck reads the text using OCR.', tint: 'bg-emerald-100 text-emerald-700' },
  { icon: ShieldCheck, title: 'Medicine information', text: 'Review product and regulatory details gathered in a single view.', tint: 'bg-violet-100 text-violet-700' },
  { icon: Clock, title: 'Scan history', text: 'Return to earlier scans whenever you need to check something again.', tint: 'bg-amber-100 text-amber-700' },
]

const STEPS = [
  { icon: Camera, title: 'Scan', text: 'Open the app and scan the barcode or the medicine label.', tint: 'bg-sky-100 text-sky-700', dot: 'bg-blue-600' },
  { icon: FileText, title: 'Get information', text: 'See the details available from supported data sources, such as name and manufacturer.', tint: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500' },
  { icon: ShieldCheck, title: 'Make informed choices', text: 'Use what you find to ask your pharmacist better questions.', tint: 'bg-violet-100 text-violet-700', dot: 'bg-violet-500' },
]

const FAQ = [
  ['What is MediCheck?', 'MediCheck is an Android app that lets you scan a medicine barcode or label and explore the product information available for it.'],
  ['Can MediCheck guarantee that a medicine is genuine?', 'No. A scan or database match cannot independently confirm authenticity. Check the packaging, buy from authorised sources, and speak to a pharmacist or regulator if something looks wrong.'],
  ['Is MediCheck a replacement for a doctor or pharmacist?', 'No. MediCheck gives you information. It does not diagnose conditions, prescribe medicines, or replace professional medical advice.'],
  ['Why is some information missing for my medicine?', 'What you see depends on the product and on the data sources MediCheck supports. If nothing is found, try scanning the label instead of the barcode.'],
]

function DownloadButton({ children = 'Download for Android', variant = 'primary', className = '', unavailableLabel = 'Download coming soon' }) {
  const base = 'inline-flex min-h-12 items-center justify-center gap-2.5 rounded-xl px-6 text-[15px] font-semibold transition focus-visible:outline-none focus-visible:ring-4'
  const styles = {
    primary: 'bg-blue-600 text-white shadow-[0_8px_20px_-8px_rgba(37,99,235,0.7)] hover:bg-blue-700 focus-visible:ring-blue-300',
    light: 'bg-white text-blue-700 hover:bg-blue-50 focus-visible:ring-white/50',
  }[variant]
  if (!APK_URL) {
    return (
      <span role="link" aria-disabled="true" title="The Android download is not available yet" className={`${base} cursor-not-allowed bg-blue-600 text-white ${className}`}>
        <Download size={18} aria-hidden="true" /> {unavailableLabel}
      </span>
    )
  }
  return (
    <a href={APK_URL} className={`${base} ${styles} ${className}`}>
      <Download size={18} aria-hidden="true" /> {children}
    </a>
  )
}

function Logo({ light = false }) {
  return (
    <a href="#home" aria-label="MediCheck home" className="inline-flex items-center gap-2.5 rounded-lg focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-300">
      <span className="relative flex h-10 w-10 items-center justify-center">
        <span className="absolute h-5 w-9 -rotate-45 rounded-full bg-gradient-to-br from-blue-500 to-blue-700" />
        <span className="absolute h-3 w-3 -rotate-45 rounded-sm bg-white" />
      </span>
      <span className={`text-[22px] font-extrabold tracking-tight ${light ? 'text-white' : 'text-[#0b1f4d]'}`}>
        Medi<span className={light ? 'text-sky-200' : 'text-blue-600'}>Check</span>
      </span>
    </a>
  )
}

function Header() {
  const [open, setOpen] = useState(false)
  const [activeSection, setActiveSection] = useState(() => window.location.hash.slice(1) || 'home')
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  useEffect(() => {
    const updateActiveSection = () => {
      let nextSection = 'home'
      for (const [, href] of NAV) {
        const section = document.getElementById(href.slice(1))
        if (section && section.getBoundingClientRect().top <= 120) nextSection = section.id
      }
      setActiveSection((current) => current === nextSection ? current : nextSection)
    }
    window.addEventListener('scroll', updateActiveSection, { passive: true })
    window.addEventListener('resize', updateActiveSection)
    window.addEventListener('hashchange', updateActiveSection)
    updateActiveSection()
    return () => {
      window.removeEventListener('scroll', updateActiveSection)
      window.removeEventListener('resize', updateActiveSection)
      window.removeEventListener('hashchange', updateActiveSection)
    }
  }, [])

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200/70 bg-white/90 backdrop-blur-md">
      <nav aria-label="Main" className="mx-auto flex h-[72px] max-w-7xl items-center justify-between gap-6 px-5 sm:px-8">
        <Logo />
        <ul className="hidden items-center gap-9 lg:flex">
          {NAV.map(([label, href]) => {
            const sectionId = href.slice(1)
            const isActive = activeSection === sectionId
            return (
              <li key={label}>
                <a href={href} aria-current={isActive ? 'location' : undefined} onClick={() => setActiveSection(sectionId)} className={`relative py-6 text-sm font-medium transition hover:text-blue-600 ${isActive ? 'text-blue-600 after:absolute after:inset-x-0 after:bottom-3 after:h-0.5 after:rounded after:bg-blue-600' : 'text-slate-600'}`}>
                  {label}
                </a>
              </li>
            )
          })}
        </ul>
        <div className="flex items-center gap-3">
          <div className="hidden sm:block"><DownloadButton variant="primary" className="!min-h-11 !px-5 !text-sm">Download app</DownloadButton></div>
          <button
            type="button"
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-200 text-slate-700 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-300 lg:hidden"
            aria-label={open ? 'Close menu' : 'Open menu'}
            aria-expanded={open}
            aria-controls="mobile-menu"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </nav>
      {open && (
        <div id="mobile-menu" className="border-t border-slate-200 bg-white px-5 pb-5 pt-3 lg:hidden">
          <ul>
            {NAV.map(([label, href]) => {
              const sectionId = href.slice(1)
              const isActive = activeSection === sectionId
              return (
                <li key={label}>
                  <a href={href} aria-current={isActive ? 'location' : undefined} onClick={() => { setActiveSection(sectionId); setOpen(false) }} className={`flex items-center justify-between border-b border-slate-100 py-3.5 text-[15px] font-medium ${isActive ? 'text-blue-600' : 'text-slate-800'}`}>
                    {label} <ChevronRight size={16} className={isActive ? 'text-blue-600' : 'text-slate-400'} />
                  </a>
                </li>
              )
            })}
          </ul>
          <div className="mt-3 flex"><DownloadButton className="w-full" /></div>
        </div>
      )}
    </header>
  )
}

function Capsule({ className, white = false }) {
  return (
    <span aria-hidden="true" className={`absolute block h-10 w-24 overflow-hidden rounded-full shadow-[0_18px_30px_-12px_rgba(30,64,175,0.35)] ${white ? 'ring-1 ring-slate-200/70' : ''} ${className}`}>
      <span className={`absolute inset-y-0 left-0 w-1/2 bg-gradient-to-b ${white ? 'from-white to-slate-100' : 'from-blue-400 to-blue-600'}`} />
      <span className="absolute inset-y-0 right-0 w-1/2 bg-gradient-to-b from-white to-slate-200" />
    </span>
  )
}

function PhoneShowcase() {
  const rows = [
    { icon: ScanLine, title: 'Scan medicine', sub: 'Check product details', tint: 'bg-sky-100 text-sky-700' },
    { icon: Clock, title: 'Scan history', sub: 'View scanned medicines', tint: 'bg-emerald-100 text-emerald-700' },
    { icon: Settings, title: 'Settings', sub: 'Manage your account', tint: 'bg-slate-100 text-slate-600' },
  ]
  return (
    <div className="relative mx-auto flex w-full max-w-[460px] items-center justify-center py-6">
      <span aria-hidden="true" className="absolute -inset-x-4 top-1/2 aspect-square -translate-y-1/2 rounded-full bg-gradient-to-b from-blue-100 to-blue-50/60" />
      <Capsule className="-left-8 top-[44%] -rotate-[40deg] sm:-left-6" />
      <Capsule className="-right-8 bottom-[32%] rotate-[40deg] opacity-95 sm:-right-6" />
      <Capsule white className="-left-1 bottom-[18%] -rotate-[45deg]" />
      <aside aria-label="Scan, verify, stay safe" className="absolute right-0 top-4 z-10 hidden w-20 min-[480px]:block">
        <p className="rotate-[-8deg] text-base font-semibold italic leading-6 text-blue-700">Scan<br />Verify<br />Stay Safe!</p>
        <svg aria-hidden="true" viewBox="0 0 80 100" fill="none" className="absolute -left-5 top-[68px] h-24 w-[76px] text-blue-600">
          <path d="M72 3C72 35 57 59 23 70" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" />
          <path d="m23 70 14-2m-14 2 5-13" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </aside>
      <div className="relative w-[250px] rounded-[40px] bg-slate-900 p-[7px] shadow-[0_40px_70px_-25px_rgba(15,35,90,0.55)] sm:w-[270px]">
        <div className="overflow-hidden rounded-[34px] bg-white">
          <div className="bg-blue-600 px-5 pb-16 pt-4 text-white">
            <div className="flex justify-between text-[10px] font-semibold"><span>9:41</span><span>5G</span></div>
            <div className="mt-4 flex items-center justify-between">
              <p className="text-lg font-bold">MediCheck</p>
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20"><HeartPulse size={14} /></span>
            </div>
          </div>
          <div className="-mt-8 px-3 pb-4">
            <div className="rounded-2xl bg-white p-5 text-center shadow-[0_10px_30px_-12px_rgba(30,64,175,0.35)] ring-1 ring-slate-100">
              <p className="text-[13px] font-bold text-[#0b1f4d]">Scan your medicine</p>
              <p className="mx-auto mt-1 max-w-[150px] text-[10px] leading-snug text-slate-500">Scan a barcode or label to see available details</p>
              <span className="mx-auto mt-4 flex h-20 w-20 items-center justify-center rounded-full bg-blue-600 text-white shadow-[0_0_0_8px_rgba(37,99,235,0.12)]">
                <ScanLine size={34} strokeWidth={1.8} />
              </span>
            </div>
            <ul className="mt-4 space-y-2">
              {rows.map(({ icon: Icon, title, sub, tint }) => (
                <li key={title} className="flex items-center gap-3 rounded-xl bg-slate-50 px-3 py-3">
                  <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${tint}`}><Icon size={15} /></span>
                  <span className="flex-1"><span className="block text-[11px] font-bold text-slate-800">{title}</span><span className="block text-[9px] text-slate-500">{sub}</span></span>
                  <ChevronRight size={13} className="text-slate-400" />
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

function Hero() {
  return (
    <section id="home" className="relative overflow-hidden bg-linear-to-b from-sky-50 via-[#edf5ff] to-white">
      <div className="mx-auto grid max-w-7xl items-center gap-10 px-5 pb-16 pt-12 sm:px-8 sm:pt-16 lg:grid-cols-[1.1fr_0.9fr] lg:gap-6 lg:pb-24 lg:pt-20">
        <div className="flex flex-col gap-6">
          <p className="inline-flex self-start items-center gap-4 rounded-full bg-blue-100/70 px-4 py-1.5 text-sm font-medium text-blue-700">
            <span>Scan</span><span aria-hidden="true">•</span><span>Verify</span><span aria-hidden="true">•</span><span>Be Safe</span>
          </p>
          <h1 className="text-[2.75rem] font-extrabold leading-[1.04] tracking-[-0.025em] text-[#0b1f4d] min-[480px]:text-[3.25rem] sm:text-6xl lg:text-[4.25rem]">
            Your Smart<br /><span className="text-blue-600">Medicine Scanner</span>
          </h1>
          <p className="max-w-lg text-xl leading-[1.4] text-slate-600">
            MediCheck helps you verify your medicines instantly using barcode and label scanning. Get accurate information about your medication, check for counterfeits, and stay safe.
          </p>
          <div className="flex flex-wrap gap-3">
            <DownloadButton unavailableLabel="Download for Android" className="rounded-full px-7 text-base" />
            <a href="#how-it-works" className="inline-flex min-h-12 items-center justify-center gap-2.5 rounded-full border border-blue-200 bg-white/70 px-7 text-base font-semibold text-blue-700 transition hover:bg-white focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-300">
              <Play size={18} aria-hidden="true" /> Watch Demo
            </a>
          </div>
          <div className="pt-4">
            <ul className="grid max-w-xl grid-cols-1 gap-5 min-[440px]:grid-cols-3">
              {[
                [ShieldCheck, 'Accurate', 'Information'],
                [Zap, 'Fast & Easy', 'to Use'],
                [HeartPulse, 'Safe', 'Health for All'],
              ].map(([Icon, a, b]) => (
                <li key={a} className="flex items-center gap-3">
                  <Icon size={30} strokeWidth={1.6} className="shrink-0 text-blue-600" aria-hidden="true" />
                  <span className="text-sm leading-tight text-slate-600">{a}<br />{b}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <PhoneShowcase />
      </div>
    </section>
  )
}

function Features() {
  return (
    <section id="features" className="scroll-mt-20 bg-white py-20 sm:py-24">
      <div className="mx-auto max-w-7xl px-5 sm:px-8">
        <div className="text-center">
          <h2 className="text-3xl font-extrabold tracking-tight text-[#0b1f4d] sm:text-4xl">Key features</h2>
          <p className="mt-3 text-lg text-slate-600">Everything you need to understand your medicines better.</p>
        </div>
        <ul className="mt-14 grid gap-x-8 gap-y-12 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ icon: Icon, title, text, tint }) => (
            <li key={title} className="text-center">
              <span className={`mx-auto flex h-20 w-20 items-center justify-center rounded-full ${tint}`}><Icon size={32} strokeWidth={1.6} aria-hidden="true" /></span>
              <h3 className="mt-5 text-lg font-bold text-[#0b1f4d]">{title}</h3>
              <p className="mx-auto mt-2 max-w-[240px] leading-7 text-slate-600">{text}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function HowItWorks() {
  return (
    <section id="how-it-works" className="scroll-mt-20 px-5 pb-20 sm:px-8 sm:pb-24">
      <div className="mx-auto max-w-7xl rounded-[28px] bg-gradient-to-b from-sky-50 to-[#f4f8ff] px-6 py-14 sm:px-12">
        <div className="text-center">
          <h2 className="text-3xl font-extrabold tracking-tight text-[#0b1f4d] sm:text-4xl">How it works</h2>
          <p className="mt-3 text-lg text-slate-600">Get started in three simple steps.</p>
        </div>
        <ol className="mt-12 grid gap-10 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-start md:gap-4">
          {STEPS.flatMap(({ icon: Icon, title, text, tint, dot }, i) => {
            const item = (
              <li key={title} className="flex flex-col items-center text-center">
                <div className="relative">
                  <span className={`flex h-20 w-20 items-center justify-center rounded-full ${tint}`}><Icon size={32} strokeWidth={1.6} aria-hidden="true" /></span>
                  <span className={`absolute -left-3 -top-1 flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold text-white ${dot}`}>{i + 1}</span>
                </div>
                <h3 className="mt-5 text-lg font-bold text-[#0b1f4d]">{title}</h3>
                <p className="mt-2 max-w-[260px] leading-7 text-slate-600">{text}</p>
              </li>
            )
            return i < STEPS.length - 1
              ? [item, <li key={`a${i}`} aria-hidden="true" className="hidden pt-7 text-blue-300 md:block"><ArrowRight size={30} strokeWidth={1.4} /></li>]
              : [item]
          })}
        </ol>
      </div>
    </section>
  )
}

function About() {
  return (
    <section id="about" className="scroll-mt-20 bg-white px-5 pb-20 sm:px-8 sm:pb-24">
      <div className="mx-auto grid max-w-7xl items-center gap-8 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16">
        <h2 className="text-3xl font-extrabold leading-tight tracking-tight text-[#0b1f4d] sm:text-4xl">Clear information helps you ask better questions.</h2>
        <p className="max-w-xl text-lg leading-8 text-slate-600">
          Medicine packaging is dense and hard to read. MediCheck brings barcode scanning, label recognition, and available regulatory data together, so the details are easier to find and easier to take to a pharmacist or doctor.
        </p>
      </div>
    </section>
  )
}

function Faq() {
  return (
    <section id="faq" className="scroll-mt-20 bg-slate-50 py-20 sm:py-24">
      <div className="mx-auto grid max-w-7xl gap-10 px-5 sm:px-8 lg:grid-cols-[0.7fr_1.3fr]">
        <h2 className="text-3xl font-extrabold tracking-tight text-[#0b1f4d] sm:text-4xl">Common questions</h2>
        <div className="divide-y divide-slate-200 border-y border-slate-200">
          {FAQ.map(([q, a]) => (
            <details key={q} className="group py-5">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 rounded-md text-left font-semibold text-[#0b1f4d] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-blue-300 [&::-webkit-details-marker]:hidden">
                {q}
                <ChevronRight size={20} aria-hidden="true" className="shrink-0 text-blue-600 transition-transform group-open:rotate-90" />
              </summary>
              <p className="mt-3 max-w-2xl leading-7 text-slate-600">{a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  )
}

function CtaBanner() {
  return (
    <section id="download" className="scroll-mt-20 px-5 py-16 sm:px-8 sm:py-20">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 rounded-[28px] bg-gradient-to-r from-blue-700 to-blue-500 px-6 py-12 text-white sm:px-12 md:flex-row md:items-center md:justify-between">
        <div className="max-w-xl">
          <p className="text-sm font-semibold uppercase tracking-wide text-blue-100">MediCheck for Android</p>
          <h2 className="mt-2 text-3xl font-extrabold tracking-tight sm:text-4xl">Download MediCheck</h2>
          <p className="mt-3 text-lg leading-8 text-blue-50">Scan a medicine and see what information is available, right from your phone.</p>
        </div>
        <div className="flex flex-col gap-2">
          <DownloadButton variant="light" />
          <p className="flex items-center gap-1.5 text-xs text-blue-100"><Smartphone size={13} aria-hidden="true" /> Check device requirements before installing.</p>
        </div>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 sm:px-8 lg:flex-row lg:items-center lg:justify-between">
        <Logo />
        <nav aria-label="Footer">
          <ul className="flex flex-wrap gap-x-7 gap-y-3 text-sm text-slate-600">
            {NAV.map(([label, href]) => <li key={label}><a href={href} className="hover:text-blue-600">{label}</a></li>)}
          </ul>
        </nav>
        <p className="text-sm text-slate-500">© {new Date().getFullYear()} MediCheck</p>
      </div>
      <p className="border-t border-slate-100 px-5 py-4 text-center text-xs leading-5 text-slate-500">
        MediCheck is informational. It is not a substitute for professional medical advice or official medicine authentication.
      </p>
    </footer>
  )
}

export default function Landing() {
  return (
    <div className="min-h-screen overflow-x-clip bg-white text-slate-800 antialiased [font-family:'Plus_Jakarta_Sans',ui-sans-serif,system-ui,sans-serif] [scroll-behavior:smooth] motion-reduce:[scroll-behavior:auto]">
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');`}</style>
      <Header />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <About />
        <Faq />
        <CtaBanner />
      </main>
      <Footer />
    </div>
  )
}