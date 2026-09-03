'use client'

import { useMemo, useState, useEffect } from 'react'
import {
  Activity, AlertTriangle, ArrowUpRight, Check, CircleDot, Cloud, Crosshair,
  Database, Gauge, GitBranch, Search, ShieldAlert, SlidersHorizontal,
  Smartphone, Store, UserRound, UsersRound, Wifi, X, Loader2
} from 'lucide-react'

type EntityType = 'applicant' | 'device' | 'dealer' | 'guarantor'
type NodeData = { id: string; type: EntityType; x: number; y: number; heat: number; detail: string }
type Scenario = { 
  id: string; 
  label: string; 
  status: string; 
  score: number; 
  tier: string; 
  confidence: string; 
  heat: number; 
  application: string; 
  summary: string; 
  recommendations: string[]; 
  drivers: string[]; 
  nodes: NodeData[]; 
  edges: [string, string][]; 
  baseline: string;
  payload: {
    application_id: string;
    applicant_id: string;
    device_hash: string;
    dealer_id: string;
    guarantor_id: string;
    bank_hash: string;
    credit_score: number;
    dti_ratio: number;
    dealer_30d_volume: number;
    is_suspicious_event: boolean;
  }
}

const scenarios: Scenario[] = [
  { 
    id: 'clean', 
    label: 'CASE #TVS-101', 
    status: 'Clean Application', 
    score: .18, 
    tier: 'STANDARD', 
    confidence: 'High', 
    heat: .18, 
    application: 'A-101', 
    summary: 'Standard borrower, single-device, unique guarantor.', 
    recommendations: ['Release application after standard KYC review', 'No dealer intervention required', 'Continue passive network monitoring'], 
    drivers: ['+0.0120 Single device relationship', '+0.0084 Credit profile', '-0.2100 Unique guarantor signal'], 
    nodes: [
      { id: 'A-101', type: 'applicant', x: 22, y: 38, heat: 0, detail: 'Standard borrower · application submitted 14:18 IST' }, 
      { id: 'DEV-C19', type: 'device', x: 48, y: 25, heat: .05, detail: 'Unique IMEI hash · 1 application / 24h' }, 
      { id: 'DLR-101', type: 'dealer', x: 76, y: 43, heat: .12, detail: 'TVS dealer · baseline volume normal' }, 
      { id: 'GTR-101', type: 'guarantor', x: 48, y: 68, heat: .04, detail: 'Unique guarantor · no recent overlap' }
    ], 
    edges: [['A-101', 'DEV-C19'], ['A-101', 'DLR-101'], ['A-101', 'GTR-101']], 
    baseline: 'Log-scaled baseline active: clean walk-in behavior is within expected volume; no alert generated.',
    payload: {
      application_id: "APP-101",
      applicant_id: "A-101",
      device_hash: "DEV-C19",
      dealer_id: "DLR-101",
      guarantor_id: "GTR-101",
      bank_hash: "BANK-101",
      credit_score: 750,
      dti_ratio: 0.20,
      dealer_30d_volume: 25,
      is_suspicious_event: false
    }
  },
  { 
    id: 'ring', 
    label: 'CASE #TVS-202', 
    status: 'Syndicate Ring Attack', 
    score: .88, 
    tier: 'SENIOR ESCALATION', 
    confidence: 'High', 
    heat: .82, 
    application: 'A-202', 
    summary: 'Rapid applications via shared IMEI Hash #999.', 
    recommendations: ['Hold disbursement immediately on Application A-202', 'Trigger physical audit for TVS Dealer DLR-202', 'Mandatory secondary verification for Guarantor GTR-404'], 
    drivers: ['+0.4123 Max Infra Heat', '+0.2850 Shared IMEI Hash #999', '+0.1205 Credit Profile', '+0.0840 Guarantor overlap'], 
    nodes: [
      { id: 'A-202', type: 'applicant', x: 18, y: 32, heat: 0, detail: 'Applicant · submitted 8 minutes after A-201' }, 
      { id: 'A-201', type: 'applicant', x: 18, y: 60, heat: 0, detail: 'Applicant · linked to same device cluster' }, 
      { id: 'A-203', type: 'applicant', x: 42, y: 16, heat: 0, detail: 'Applicant · third rapid application' }, 
      { id: 'DEV-999', type: 'device', x: 48, y: 45, heat: .98, detail: 'IMEI Hash #999 · 5 applications in 8 minutes' }, 
      { id: 'DLR-202', type: 'dealer', x: 78, y: 42, heat: .86, detail: 'TVS Dealer / DSA · 4.2x baseline heat' }, 
      { id: 'GTR-404', type: 'guarantor', x: 48, y: 76, heat: .77, detail: 'Field executive · shared across 4 applications' }
    ], 
    edges: [['A-202', 'DEV-999'], ['A-201', 'DEV-999'], ['A-203', 'DEV-999'], ['A-202', 'DLR-202'], ['A-201', 'DLR-202'], ['A-203', 'DLR-202'], ['A-202', 'GTR-404'], ['A-201', 'GTR-404'], ['A-203', 'GTR-404']], 
    baseline: 'Log-scaled baseline active: normal dealer volume is dampened, but shared IMEI and guarantor signals exceed suppression thresholds.',
    payload: {
      application_id: "APP-202",
      applicant_id: "A-202",
      device_hash: "DEV-999",
      dealer_id: "DLR-202",
      guarantor_id: "GTR-404",
      bank_hash: "BANK-999",
      credit_score: 580,
      dti_ratio: 0.65,
      dealer_30d_volume: 120,
      is_suspicious_event: true
    }
  },
  { 
    id: 'rural', 
    label: 'CASE #TVS-303', 
    status: 'Rural High-Volume Dealer', 
    score: .43, 
    tier: 'ENHANCED VERIFICATION', 
    confidence: 'Medium', 
    heat: .46, 
    application: 'A-303', 
    summary: 'Seasonal high-volume TVS Dealer #777.', 
    recommendations: ['Request a second field-verifiable identity document', 'Sample 10% of DLR-777 files for quality review', 'Keep disbursement pending until address match completes'], 
    drivers: ['+0.1640 Dealer volume above baseline', '+0.0910 Shared device cluster', '-0.0800 Seasonal volume dampening'], 
    nodes: [
      { id: 'A-303', type: 'applicant', x: 25, y: 48, heat: 0, detail: 'Applicant · rural branch · address match pending' }, 
      { id: 'A-304', type: 'applicant', x: 25, y: 70, heat: 0, detail: 'Applicant · same seasonal dealer cohort' }, 
      { id: 'DEV-711', type: 'device', x: 48, y: 29, heat: .45, detail: 'Shared field device · 2 applications / 30d' }, 
      { id: 'DEV-712', type: 'device', x: 48, y: 74, heat: .39, detail: 'Shared field device · 2 applications / 30d' }, 
      { id: 'DLR-777', type: 'dealer', x: 78, y: 49, heat: .58, detail: 'TVS Dealer #777 · seasonal volume dampening active' }, 
      { id: 'GTR-303', type: 'guarantor', x: 48, y: 51, heat: .34, detail: 'Field executive · rural territory' }
    ], 
    edges: [['A-303', 'DEV-711'], ['A-304', 'DEV-712'], ['A-303', 'DLR-777'], ['A-304', 'DLR-777'], ['A-303', 'GTR-303'], ['A-304', 'GTR-303']], 
    baseline: 'Log-scaled baseline active: seasonal dealer volume is dampened against historical rural trade before scoring.',
    payload: {
      application_id: "APP-303",
      applicant_id: "A-303",
      device_hash: "DEV-711",
      dealer_id: "DLR-777",
      guarantor_id: "GTR-303",
      bank_hash: "BANK-777",
      credit_score: 670,
      dti_ratio: 0.35,
      dealer_30d_volume: 300,
      is_suspicious_event: false
    }
  },
]

const meta = { 
  applicant: { label: 'Applicant', color: '#3b82f6', icon: UserRound }, 
  device: { label: 'Device / IMEI', color: '#ef4444', icon: Smartphone }, 
  dealer: { label: 'TVS Dealer / DSA', color: '#8b5cf6', icon: Store }, 
  guarantor: { label: 'Guarantor / Field Executive', color: '#eab308', icon: UsersRound } 
}

export default function Page() {
  const [scenarioId, setScenarioId] = useState('ring')
  const [query, setQuery] = useState('')
  const [heat, setHeat] = useState(.82)
  const [selectedNode, setSelectedNode] = useState<NodeData | null>(null)
  const [toast, setToast] = useState('')

  // --- API INTEGRATION STATE ---
  const [apiData, setApiData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [apiOnline, setApiOnline] = useState(false)

  const scenario = scenarios.find(s => s.id === scenarioId) ?? scenarios[1]
  const matching = useMemo(() => scenario.nodes.filter(n => `${n.id} ${meta[n.type].label}`.toLowerCase().includes(query.toLowerCase())), [scenario, query])
  const nodeMap = useMemo(() => new Map(scenario.nodes.map(n => [n.id, n])))

  // --- FASTAPI FETCH FUNCTION ---
  const triggerBackendAnalysis = async (currentScenario: Scenario, customHeat?: number) => {
    setLoading(true)
    try {
      const payload = {
        ...currentScenario.payload,
        is_suspicious_event: (customHeat !== undefined ? customHeat : currentScenario.heat) > 0.5
      }

      const response = await fetch('http://localhost:8000/analyze-loan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      if (response.ok) {
        const data = await response.json()
        setApiData(data)
        setApiOnline(true)
      } else {
        setApiOnline(false)
      }
    } catch (err) {
      console.warn("Backend server unreachable, falling back to local static simulation.")
      setApiOnline(false)
      setApiData(null)
    } finally {
      setLoading(false)
    }
  }

  // Trigger API request on scenario or slider change
  useEffect(() => {
    triggerBackendAnalysis(scenario, heat)
  }, [scenarioId, heat])

  function selectScenario(id: string) { 
    const next = scenarios.find(s => s.id === id) ?? scenarios[1]; 
    setScenarioId(id); 
    setHeat(next.heat); 
    setSelectedNode(null); 
    setToast('') 
  }

  function decide(action: string) { 
    setToast(`${action} recorded for ${scenario.application}`); 
    setTimeout(() => setToast(''), 2800) 
  }

  // Dynamic Tier and Score (API Response takes priority over static simulation)
  const displayScore = apiData ? apiData.risk_score : scenario.score
  const displayTier = apiData ? apiData.risk_tier : (heat < .4 ? 'ENHANCED VERIFICATION' : scenario.tier)
  const displayDrivers = apiData ? apiData.top_drivers : scenario.drivers

  return <main className="min-h-screen bg-background text-foreground">
    <header className="border-b border-border bg-card/90 px-4 py-3 backdrop-blur-xl md:px-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg border border-primary/40 bg-primary/10 text-primary">
            <Crosshair className="size-5" />
          </div>
          <div>
            <div className="font-mono text-sm font-bold tracking-[.18em] text-primary">NEXUS</div>
            <div className="text-xs text-muted-foreground">Risk Operations Workbench</div>
          </div>
          <span className={`status-live ${apiOnline ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30' : 'bg-amber-500/10 text-amber-400 border-amber-500/30'} border px-2 py-0.5 rounded text-[10px] flex items-center gap-1.5`}>
            <span className={`size-1.5 rounded-full ${apiOnline ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'}`} /> 
            {apiOnline ? 'LIVE API CONNECTED' : 'OFFLINE MODE (LOCAL)'}
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Metric icon={<Gauge />} label="Detection lead time" value="-42%" />
          <Metric icon={<AlertTriangle />} label="False positive rate" value="1.2%" />
          <Metric icon={<ArrowUpRight />} label="Prevented loss" value="₹1.4 Cr" />
          <Metric icon={<Wifi />} label="System status" value={apiOnline ? "API Active" : "Sub-second"} green={apiOnline} />
        </div>
      </div>
    </header>

    <div className="mx-auto max-w-[1700px] p-4 md:p-6">
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="eyebrow"><Activity className="size-3.5" /> INVESTIGATION CONSOLE / TVS CREDIT</div>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-3xl">Coordinated lending risk analysis</h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="size-2 rounded-full bg-emerald-400" /> Last sync 14:32:08 IST <Cloud className="ml-2 size-3.5" />
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[230px_minmax(0,1fr)_390px]">
        {/* CASE QUEUE */}
        <aside className="panel p-4">
          <div className="eyebrow">CASE TRIAGE QUEUE</div>
          <div className="mt-1 text-sm font-semibold">Active investigations</div>
          <div className="mt-4 space-y-2">
            {scenarios.map(s => (
              <button 
                key={s.id} 
                onClick={() => selectScenario(s.id)} 
                className={`w-full rounded-md border p-3 text-left transition ${scenarioId === s.id ? 'border-primary bg-primary/10' : 'border-border bg-background/40 hover:border-primary/50'}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] font-bold">{s.label}</span>
                  <span className={`size-2 rounded-full ${s.id === 'clean' ? 'bg-emerald-400' : s.id === 'ring' ? 'bg-red-400' : 'bg-yellow-400'}`} />
                </div>
                <div className="mt-1 text-xs font-medium">{s.status}</div>
                <div className="mt-2 text-[10px] leading-4 text-muted-foreground">{s.summary}</div>
                <div className="mt-2 font-mono text-[10px] text-primary">{s.tier} · {s.score.toFixed(2)}</div>
              </button>
            ))}
          </div>
          <div className="mt-6 border-t border-border pt-4">
            <div className="eyebrow">ENTITY FILTER</div>
            <div className="relative mt-2">
              <Search className="absolute left-3 top-2.5 size-4 text-muted-foreground" />
              <input 
                aria-label="Search graph nodes" 
                value={query} 
                onChange={e => setQuery(e.target.value)} 
                placeholder="ID or entity type" 
                className="h-9 w-full rounded-md border border-input bg-background/80 pl-9 pr-3 text-xs outline-none focus:border-primary" 
              />
            </div>
            <div className="mt-3 text-[10px] text-muted-foreground">{matching.length} of {scenario.nodes.length} nodes visible</div>
          </div>
        </aside>

        {/* GRAPH TOPOLOGY */}
        <section className="panel flex min-h-[620px] flex-col overflow-hidden">
          <div className="border-b border-border p-4 flex items-center justify-between">
            <div>
              <div className="eyebrow">STIGMERGIC HEAT ENGINE</div>
              <h2 className="mt-1 text-base font-semibold">Live Network Topology</h2>
              <div className="mt-2 text-xs text-muted-foreground">Tap any entity to inspect node metadata. Applicant nodes carry a zero-bleed heat guarantee.</div>
            </div>
            {loading && <Loader2 className="size-5 animate-spin text-primary" />}
          </div>
          <div className="graph-wrap m-4 flex-1">
            <svg viewBox="0 0 100 100" className="h-full min-h-[390px] w-full" role="img" aria-label="Interactive network topology graph">
              <defs>
                <pattern id="grid" width="8" height="8" patternUnits="userSpaceOnUse">
                  <path d="M8 0H0V8" fill="none" stroke="rgba(148,163,184,.08)" strokeWidth=".15" />
                </pattern>
              </defs>
              <rect width="100" height="100" fill="url(#grid)" />
              {scenario.edges.map(([from, to], i) => { 
                const a = nodeMap.get(from); 
                const b = nodeMap.get(to); 
                return a && b ? <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="graph-edge" /> : null 
              })}
              {matching.map(n => { 
                const m = meta[n.type]; 
                const size = n.type === 'applicant' ? 5.2 : 5 + n.heat * 3; 
                return (
                  <g key={n.id} onClick={() => setSelectedNode(n)} className="cursor-pointer" role="button" aria-label={`Inspect ${n.id}`}>
                    <circle cx={n.x} cy={n.y} r={size + 2} fill="transparent" stroke={n.type === 'device' && n.heat > .7 ? '#ef4444' : 'transparent'} strokeWidth=".7" className={n.type === 'device' && n.heat > .7 ? 'node-hot' : ''} />
                    {n.type === 'applicant' ? (
                      <ellipse cx={n.x} cy={n.y} rx="5.2" ry="3.8" fill="#3b82f6" stroke="#bfdbfe" strokeWidth=".5" />
                    ) : n.type === 'dealer' ? (
                      <rect x={n.x - size} y={n.y - size} width={size * 2} height={size * 2} rx="1" fill="#8b5cf6" stroke="#ddd6fe" strokeWidth=".5" />
                    ) : (
                      <polygon points={`${n.x},${n.y-size} ${n.x+size},${n.y} ${n.x},${n.y+size} ${n.x-size},${n.y}`} fill={n.type === 'guarantor' ? '#eab308' : `rgba(239,68,68,${.35 + n.heat * .65})`} stroke={n.type === 'guarantor' ? '#fef08a' : '#fecaca'} strokeWidth=".5" />
                    )}
                    {n.type === 'applicant' && <text x={n.x} y={n.y + 1} textAnchor="middle" className="fill-white text-[2.2px] font-bold">A</text>}
                    <text x={n.x + 7} y={n.y + 1} className="graph-label">{n.id}</text>
                  </g>
                )
              })}
            </svg>
            {selectedNode && (
              <div className="absolute bottom-4 left-4 right-4 flex items-start justify-between rounded-md border border-primary/40 bg-card/95 p-3 text-xs shadow-xl backdrop-blur">
                <div>
                  <div className="font-mono font-bold text-primary">{selectedNode.id}</div>
                  <div className="mt-1 text-muted-foreground">{meta[selectedNode.type].label} · Heat = {selectedNode.type === 'applicant' ? '0.0' : selectedNode.heat.toFixed(2)}</div>
                  <div className="mt-1 text-foreground/80">{selectedNode.detail}</div>
                </div>
                <button aria-label="Close node inspection" onClick={() => setSelectedNode(null)}>
                  <X className="size-4 text-muted-foreground" />
                </button>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-4 border-t border-border px-4 py-3 text-[10px] text-muted-foreground">
            {Object.entries(meta).map(([key, m]) => (
              <span key={key} className="flex items-center gap-1.5">
                <span className="size-2 rounded-sm" style={{ backgroundColor: m.color }} />
                {m.label}
              </span>
            ))}
          </div>
        </section>

        {/* DECISION TIER & SHAP PANEL */}
        <aside className="panel flex flex-col overflow-hidden">
          <div className={`risk-banner ${scenario.id === 'clean' ? 'risk-banner-safe' : scenario.id === 'rural' ? 'risk-banner-warn' : ''}`}>
            <div>
              <div className="eyebrow">DECISION TIER</div>
              <div className="mt-1 text-lg font-bold">{displayTier}</div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                Risk Score: {typeof displayScore === 'number' ? displayScore.toFixed(2) : displayScore} · Confidence: {scenario.confidence}
              </div>
            </div>
            <ShieldAlert className="size-8 text-primary" />
          </div>

          <div className="space-y-4 p-4">
            <section>
              <SectionTitle icon={<ZapIcon />} title="SHAP Explainability" />
              <div className="space-y-2">
                {displayDrivers.map((d: string) => (
                  <div key={d} className="driver"><span className="driver-index">+</span><span>{d}</span></div>
                ))}
              </div>
            </section>

            <section>
              <SectionTitle icon={<AlertTriangle />} title="Recommended Next Steps" />
              <div className="space-y-2">
                {scenario.recommendations.map(r => (
                  <div key={r} className="recommendation">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-400" />
                    <span>{r}</span>
                  </div>
                ))}
              </div>
            </section>

            <section className="counterfactual">
              <SectionTitle icon={<SlidersHorizontal />} title="Counterfactual Simulator" />
              <blockquote>
                {apiData?.counterfactual ? apiData.counterfactual : "“If heat drops below 0.40, Senior Escalation reverts to Enhanced Verification.”"}
              </blockquote>
              <div className="mt-4 flex items-center justify-between font-mono text-xs">
                <span>Simulated heat</span>
                <span className={heat < .4 ? 'text-emerald-400' : 'text-amber-400'}>{heat.toFixed(2)} → {displayTier}</span>
              </div>
              <input 
                aria-label="Simulate network heat" 
                type="range" 
                min="0" 
                max="1" 
                step=".01" 
                value={heat} 
                onChange={e => setHeat(Number(e.target.value))} 
                className="mt-3 w-full accent-amber-500" 
              />
            </section>

            <div className="callout">
              <Database className="size-4 shrink-0 text-primary" />
              <span>{scenario.baseline}</span>
            </div>
          </div>

          <div className="mt-auto border-t border-border bg-background/40 p-4">
            <div className="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
              <CircleDot className="size-3.5 text-primary" />Record analyst decision
            </div>
            <div className="grid grid-cols-3 gap-2">
              <ActionButton label="Hold" tone="amber" onClick={() => decide('Hold Disbursement')} />
              <ActionButton label="Escalate" tone="red" onClick={() => decide('Escalate Case')} />
              <ActionButton label="Approve" tone="green" onClick={() => decide('Approve / Clear')} />
            </div>
          </div>
        </aside>
      </div>
    </div>

    {toast && (
      <div role="status" className="fixed bottom-5 right-5 flex items-center gap-2 rounded-md border border-primary/40 bg-card px-4 py-3 text-sm shadow-2xl">
        <Check className="size-4 text-emerald-400" />{toast}
      </div>
    )}
  </main>
}

function Metric({ icon, label, value, green = false }: { icon: React.ReactNode; label: string; value: string; green?: boolean }) { 
  return (
    <div className="metric">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-muted-foreground">{icon}{label}</div>
      <div className={`mt-1 font-mono text-sm font-semibold ${green ? 'text-emerald-400' : 'text-foreground'}`}>{value}</div>
    </div>
  ) 
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) { 
  return (
    <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[.12em] text-muted-foreground">{icon}<span>{title}</span></div>
  ) 
}

function ActionButton({ label, tone, onClick }: { label: string; tone: 'green' | 'amber' | 'red'; onClick: () => void }) { 
  return (
    <button onClick={onClick} className={`action action-${tone}`}><Check className="size-3.5" />{label}</button>
  ) 
}

function ZapIcon() { 
  return <GitBranch className="size-3.5" /> 
}