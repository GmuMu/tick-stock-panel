import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpen, Check, ClipboardList, FileClock, GitBranch, Plus, ShieldCheck, X, type LucideIcon } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { api, type DecisionGate, type JournalEntry, type TradingPlan, type TradingResearchSummary, type TradingThesis } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

type Tab = 'thesis' | 'plans' | 'decisions' | 'journal' | 'audit'

const SUMMARY_CARDS: [keyof TradingResearchSummary, string, LucideIcon][] = [
  ['theses', 'Thesis', BookOpen],
  ['plans', '计划', ClipboardList],
  ['decisions', '决策门', ShieldCheck],
  ['journal', '日志', FileClock],
  ['audit_events', '审计事件', GitBranch],
]

const inputCls = 'w-full rounded-btn border border-border bg-base px-3 py-2 text-xs text-foreground outline-none focus:border-accent'
const cardCls = 'rounded-card border border-border bg-surface/70 p-4 shadow-sm'

function keyFor(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function Status({ value }: { value: string }) {
  const tone = value === 'approved' || value === 'active' || value === 'confirmed'
    ? 'text-bull border-bull/30 bg-bull/10'
    : value === 'rejected' || value === 'cancelled' || value === 'invalidated'
      ? 'text-bear border-bear/30 bg-bear/10'
      : 'text-warning border-warning/30 bg-warning/10'
  return <span className={cn('rounded-full border px-2 py-0.5 text-[10px]', tone)}>{value}</span>
}

export function TradingResearch() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('thesis')
  const summary = useQuery({ queryKey: QK.tradingResearchSummary, queryFn: api.tradingResearchSummary })
  const theses = useQuery({ queryKey: QK.tradingTheses, queryFn: api.tradingTheses })
  const plans = useQuery({ queryKey: QK.tradingPlans, queryFn: api.tradingPlans })
  const decisions = useQuery({ queryKey: QK.tradingDecisions, queryFn: api.tradingDecisions })
  const journal = useQuery({ queryKey: QK.tradingJournal, queryFn: api.tradingJournal })
  const audit = useQuery({ queryKey: QK.tradingAudit, queryFn: api.tradingAudit, enabled: tab === 'audit' })

  const refresh = () => {
    for (const key of [QK.tradingResearchSummary, QK.tradingTheses, QK.tradingPlans, QK.tradingDecisions, QK.tradingJournal, QK.tradingAudit]) {
      qc.invalidateQueries({ queryKey: key })
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="交易研究"
        subtitle="Thesis → Trade Plan → Decision Gate → Journal · 仅研究与纸面记录，不会真实下单"
        right={<span className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent/10 px-2 py-1 text-[10px] text-accent"><ShieldCheck className="h-3 w-3" />审计已开启</span>}
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        <div className="mx-auto max-w-6xl space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {SUMMARY_CARDS.map(([key, label, Icon]) => (
              <div key={String(key)} className={cardCls}>
                <div className="flex items-center gap-2 text-[11px] text-muted"><Icon className="h-3.5 w-3.5 text-accent" />{label}</div>
                <div className="mt-2 font-mono text-xl text-foreground">{summary.data?.[key as keyof typeof summary.data] ?? '—'}</div>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-1 border-b border-border/70 pb-2">
            {([
              ['thesis', 'Thesis 论点'], ['plans', 'Trade Plan'], ['decisions', 'Decision Gate'],
              ['journal', 'Journal'], ['audit', '审计只读'],
            ] as [Tab, string][]).map(([value, label]) => (
              <button key={value} onClick={() => setTab(value)} className={cn('rounded-btn px-3 py-1.5 text-xs transition-colors cursor-pointer', tab === value ? 'bg-accent text-white' : 'text-secondary hover:bg-elevated')}>
                {label}
              </button>
            ))}
          </div>

          {tab === 'thesis' && <ThesisPanel items={theses.data?.items ?? []} onSaved={refresh} />}
          {tab === 'plans' && <PlansPanel theses={theses.data?.items ?? []} items={plans.data?.items ?? []} onSaved={refresh} />}
          {tab === 'decisions' && <DecisionsPanel plans={plans.data?.items ?? []} items={decisions.data?.items ?? []} onSaved={refresh} />}
          {tab === 'journal' && <JournalPanel plans={plans.data?.items ?? []} decisions={decisions.data?.items ?? []} items={journal.data?.items ?? []} onSaved={refresh} />}
          {tab === 'audit' && <AuditPanel items={audit.data?.items ?? []} loading={audit.isLoading} onRetry={() => audit.refetch()} />}
        </div>
      </div>
    </div>
  )
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="space-y-3"><h2 className="flex items-center gap-2 text-xs font-semibold text-foreground"><span className="h-3 w-0.5 rounded-full bg-accent" />{title}</h2>{children}</section>
}

function ThesisPanel({ items, onSaved }: { items: TradingThesis[]; onSaved: () => void }) {
  const [form, setForm] = useState({ symbol: '', title: '', hypothesis: '', evidence: '', counter_evidence: '' })
  const mutation = useMutation({
    mutationFn: () => api.tradingThesisCreate({
      symbol: form.symbol.trim().toUpperCase(), title: form.title.trim(), direction: 'long', hypothesis: form.hypothesis.trim(),
      evidence: form.evidence.split('\n').map(s => s.trim()).filter(Boolean), counter_evidence: form.counter_evidence.split('\n').map(s => s.trim()).filter(Boolean), status: 'open', metadata: {}, idempotency_key: keyFor('thesis'),
    } as any),
    onSuccess: () => { setForm({ symbol: '', title: '', hypothesis: '', evidence: '', counter_evidence: '' }); onSaved() },
  })
  return <Panel title="研究论点"><div className="grid gap-3 lg:grid-cols-[20rem_1fr]">
    <div className={cn(cardCls, 'space-y-2')}>
      <input className={inputCls} placeholder="标的，如 000001.SZ" value={form.symbol} onChange={e => setForm({ ...form, symbol: e.target.value })} />
      <input className={inputCls} placeholder="论点标题" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} />
      <textarea className={cn(inputCls, 'min-h-24')} placeholder="核心假设：为什么值得跟踪？" value={form.hypothesis} onChange={e => setForm({ ...form, hypothesis: e.target.value })} />
      <textarea className={cn(inputCls, 'min-h-16')} placeholder="证据，每行一条" value={form.evidence} onChange={e => setForm({ ...form, evidence: e.target.value })} />
      <textarea className={cn(inputCls, 'min-h-16')} placeholder="反证/失效条件，每行一条" value={form.counter_evidence} onChange={e => setForm({ ...form, counter_evidence: e.target.value })} />
      <button disabled={mutation.isPending || !form.symbol.trim() || !form.title.trim() || !form.hypothesis.trim()} onClick={() => mutation.mutate()} className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50 cursor-pointer"><Plus className="h-3.5 w-3.5" />保存 Thesis</button>
    </div>
    <div className="space-y-2">{items.length === 0 ? <Empty text="还没有研究论点，先建立一个可证伪的假设。" /> : items.map(item => <article key={item.id} className={cardCls}><div className="flex items-center gap-2"><span className="font-mono text-sm text-foreground">{item.symbol}</span><Status value={item.status} /><span className="ml-auto text-[10px] text-muted">v{item.version} · r{item.revision}</span></div><div className="mt-1 text-sm font-medium">{item.title}</div><p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-secondary">{item.hypothesis}</p><div className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2"><div><span className="text-muted">证据</span><ul className="mt-1 space-y-1 text-secondary">{item.evidence.map((v, i) => <li key={i}>+ {v}</li>)}</ul></div><div><span className="text-muted">反证</span><ul className="mt-1 space-y-1 text-secondary">{item.counter_evidence.map((v, i) => <li key={i}>- {v}</li>)}</ul></div></div></article>)}</div>
  </div></Panel>
}

function PlansPanel({ theses, items, onSaved }: { theses: TradingThesis[]; items: TradingPlan[]; onSaved: () => void }) {
  const [form, setForm] = useState({ symbol: '', thesis_id: '', entry_price: '', stop_price: '', target_price: '', position_pct: '', notes: '' })
  const mutation = useMutation({ mutationFn: () => api.tradingPlanCreate({ symbol: form.symbol.trim().toUpperCase(), thesis_id: form.thesis_id || null, direction: 'buy', entry_price: form.entry_price ? Number(form.entry_price) : null, stop_price: form.stop_price ? Number(form.stop_price) : null, target_price: form.target_price ? Number(form.target_price) : null, position_pct: form.position_pct ? Number(form.position_pct) : null, quantity: null, valid_from: null, valid_until: null, candidate_source: { source: 'manual_research' }, status: 'draft', notes: form.notes, idempotency_key: keyFor('plan') } as any), onSuccess: () => { setForm({ symbol: '', thesis_id: '', entry_price: '', stop_price: '', target_price: '', position_pct: '', notes: '' }); onSaved() } })
  return <Panel title="结构化交易计划"><div className="grid gap-3 lg:grid-cols-[20rem_1fr]"><div className={cn(cardCls, 'space-y-2')}><input className={inputCls} placeholder="标的" value={form.symbol} onChange={e => setForm({ ...form, symbol: e.target.value })} /><select className={inputCls} value={form.thesis_id} onChange={e => setForm({ ...form, thesis_id: e.target.value })}><option value="">不关联 Thesis</option>{theses.map(t => <option key={t.id} value={t.id}>{t.symbol} · {t.title}</option>)}</select><div className="grid grid-cols-2 gap-2">{(['entry_price', 'stop_price', 'target_price', 'position_pct'] as const).map(key => <input key={key} className={inputCls} type="number" placeholder={{ entry_price: '入场价', stop_price: '止损价', target_price: '目标价', position_pct: '仓位%' }[key]} value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} />)}</div><textarea className={cn(inputCls, 'min-h-20')} placeholder="执行备注与失效条件" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} /><button disabled={mutation.isPending || !form.symbol.trim()} onClick={() => mutation.mutate()} className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50 cursor-pointer"><Plus className="h-3.5 w-3.5" />保存计划</button></div><div className="space-y-2">{items.length === 0 ? <Empty text="还没有交易计划。" /> : items.map(p => <PlanCard key={p.id} plan={p} />)}</div></div></Panel>
}

function PlanCard({ plan }: { plan: TradingPlan }) {
  return <article className={cardCls}><div className="flex items-center gap-2"><span className="font-mono text-sm">{plan.symbol}</span><Status value={plan.status} /><span className="ml-auto text-[10px] text-muted">r{plan.revision}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-xs text-secondary sm:grid-cols-4"><span>入场 <b className="font-mono text-foreground">{plan.entry_price ?? '—'}</b></span><span>止损 <b className="font-mono text-bear">{plan.stop_price ?? '—'}</b></span><span>目标 <b className="font-mono text-bull">{plan.target_price ?? '—'}</b></span><span>仓位 <b className="font-mono text-foreground">{plan.position_pct != null ? `${plan.position_pct}%` : '—'}</b></span></div>{plan.notes && <p className="mt-2 text-xs text-secondary">{plan.notes}</p>}</article>
}

function DecisionsPanel({ plans, items, onSaved }: { plans: TradingPlan[]; items: DecisionGate[]; onSaved: () => void }) {
  const create = useMutation({ mutationFn: (plan_id: string) => api.tradingDecisionCreate({ plan_id, status: 'pending', rationale: '', idempotency_key: keyFor('gate') }), onSuccess: onSaved })
  const transition = useMutation({ mutationFn: ({ item, status }: { item: DecisionGate; status: DecisionGate['status'] }) => api.tradingDecisionTransition(item.id, { status, rationale: status === 'approved' ? '人工确认通过' : '人工确认未通过', expected_revision: item.revision, idempotency_key: keyFor('transition') }), onSuccess: onSaved })
  const existing = new Set(items.map(item => item.plan_id))
  return <Panel title="决策门"><div className="space-y-2">{plans.length === 0 ? <Empty text="先创建 Trade Plan，才能进入决策门。" /> : plans.map(plan => { const gate = items.find(item => item.plan_id === plan.id); return <article key={plan.id} className={cardCls}><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm">{plan.symbol}</span><span className="text-xs text-secondary">{plan.id}</span>{gate ? <Status value={gate.status} /> : <span className="text-[10px] text-muted">尚未建立决策门</span>}<span className="ml-auto flex gap-1">{!gate && !existing.has(plan.id) && <button onClick={() => create.mutate(plan.id)} className="rounded-btn border border-accent/30 px-2 py-1 text-[10px] text-accent hover:bg-accent/10 cursor-pointer">建立决策门</button>}{gate?.status === 'pending' && <><button onClick={() => transition.mutate({ item: gate, status: 'approved' })} className="inline-flex items-center gap-1 rounded-btn border border-bull/30 px-2 py-1 text-[10px] text-bull hover:bg-bull/10 cursor-pointer"><Check className="h-3 w-3" />批准</button><button onClick={() => transition.mutate({ item: gate, status: 'rejected' })} className="inline-flex items-center gap-1 rounded-btn border border-bear/30 px-2 py-1 text-[10px] text-bear hover:bg-bear/10 cursor-pointer"><X className="h-3 w-3" />拒绝</button></>}</span></div>{gate?.rationale && <p className="mt-2 text-xs text-secondary">{gate.rationale}</p>}</article> })}</div></Panel>
}

function JournalPanel({ plans, decisions, items, onSaved }: { plans: TradingPlan[]; decisions: DecisionGate[]; items: JournalEntry[]; onSaved: () => void }) {
  const [form, setForm] = useState({ kind: 'note' as JournalEntry['kind'], plan_id: '', decision_id: '', content: '' })
  const mutation = useMutation({ mutationFn: () => api.tradingJournalCreate({ kind: form.kind, plan_id: form.plan_id || null, decision_id: form.decision_id || null, content: form.content.trim(), payload: {}, occurred_at: new Date().toISOString(), idempotency_key: keyFor('journal') } as any), onSuccess: () => { setForm({ ...form, content: '' }); onSaved() } })
  return <Panel title="交易日志"><div className="grid gap-3 lg:grid-cols-[20rem_1fr]"><div className={cn(cardCls, 'space-y-2')}><select className={inputCls} value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value as JournalEntry['kind'] })}>{['note', 'plan', 'decision', 'order', 'fill', 'review'].map(k => <option key={k} value={k}>{k}</option>)}</select><select className={inputCls} value={form.plan_id} onChange={e => setForm({ ...form, plan_id: e.target.value })}><option value="">不关联计划</option>{plans.map(p => <option key={p.id} value={p.id}>{p.symbol} · {p.id}</option>)}</select><select className={inputCls} value={form.decision_id} onChange={e => setForm({ ...form, decision_id: e.target.value })}><option value="">不关联决策</option>{decisions.map(d => <option key={d.id} value={d.id}>{d.id} · {d.status}</option>)}</select><textarea className={cn(inputCls, 'min-h-28')} placeholder="记录计划、决定、订单预留字段或复盘" value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} /><button disabled={mutation.isPending || !form.content.trim()} onClick={() => mutation.mutate()} className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50 cursor-pointer"><Plus className="h-3.5 w-3.5" />写入日志</button></div><div className="space-y-2">{items.length === 0 ? <Empty text="还没有日志。" /> : items.map(item => <article key={item.id} className={cardCls}><div className="flex items-center gap-2"><Status value={item.kind} /><span className="text-[10px] text-muted">{item.occurred_at}</span></div><p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-secondary">{item.content}</p></article>)}</div></div></Panel>
}

function AuditPanel({ items, loading, onRetry }: { items: Record<string, unknown>[]; loading: boolean; onRetry: () => void }) {
  if (loading) return <Panel title="不可变审计事件"><div className={cn(cardCls, 'py-12 text-center text-xs text-muted')}>加载中…</div></Panel>
  return <Panel title="不可变审计事件"><div className="space-y-2">{items.length === 0 ? <Empty text="暂无审计事件。" /> : items.map(item => <article key={String(item.id)} className={cardCls}><div className="flex flex-wrap items-center gap-2 text-xs"><span className="font-mono text-accent">{String(item.entity_type)}</span><span className="font-mono text-secondary">{String(item.entity_id)}</span><Status value={String(item.action)} /><span className="ml-auto text-[10px] text-muted">revision {String(item.revision)} · {String(item.created_at)}</span></div></article>)}</div><button onClick={onRetry} className="mt-3 rounded-btn border border-border px-3 py-1.5 text-xs text-secondary hover:bg-elevated cursor-pointer">刷新审计</button></Panel>
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-card border border-dashed border-border px-6 py-12 text-center text-xs text-muted">{text}</div>
}
