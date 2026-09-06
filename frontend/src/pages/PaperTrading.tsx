import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, CircleAlert, ClipboardCheck, Layers3, PackageCheck, Plus, RefreshCw, Send, ShieldCheck } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { api, type PaperOrder, type TradingPlan } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

type Tab = 'overview' | 'signals' | 'orders' | 'positions' | 'reviews' | 'outbox'
const card = 'rounded-card border border-border bg-surface/70 p-4 shadow-sm'
const input = 'w-full rounded-btn border border-border bg-base px-3 py-2 text-xs text-foreground outline-none focus:border-accent'

function keyFor(prefix: string) { return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}` }

export function PaperTrading() {
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const summary = useQuery({ queryKey: QK.paperSummary, queryFn: api.paperSummary })
  const signals = useQuery({ queryKey: QK.paperSignals, queryFn: api.paperSignals })
  const plans = useQuery({ queryKey: QK.tradingPlans, queryFn: api.tradingPlans })
  const risk = useQuery({ queryKey: QK.paperRiskChecks, queryFn: api.paperRiskChecks })
  const orders = useQuery({ queryKey: QK.paperOrders, queryFn: api.paperOrders })
  const fills = useQuery({ queryKey: QK.paperFills, queryFn: api.paperFills })
  const positions = useQuery({ queryKey: QK.paperPositions, queryFn: api.paperPositions })
  const outbox = useQuery({ queryKey: QK.paperOutbox, queryFn: api.paperOutbox })
  const reviews = useQuery({ queryKey: QK.paperReviews, queryFn: api.paperReviews })
  const refresh = () => [QK.paperSummary, QK.paperSignals, QK.paperRiskChecks, QK.paperOrders, QK.paperFills, QK.paperPositions, QK.paperOutbox, QK.paperReviews].forEach(key => qc.invalidateQueries({ queryKey: key }))

  return <div className="flex h-full min-h-0 flex-col">
    <PageHeader title="纸面交易闭环" subtitle="Unified Signal → Decision Gate → Risk → Paper OMS → Fill → Position Projection · 不连接真实券商" right={<button onClick={refresh} className="inline-flex items-center gap-1 rounded-btn border border-border px-2 py-1 text-[11px] text-secondary hover:bg-elevated cursor-pointer"><RefreshCw className="h-3 w-3" />刷新</button>} />
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4"><div className="mx-auto max-w-6xl space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">{[
        ['signals', 'Signals'], ['risk_checks', 'Risk'], ['orders', '订单'], ['fills', '成交'], ['positions', '持仓'], ['outbox_pending', '待投递'], ['reviews', '复盘'],
      ].map(([key, label]) => <div key={key} className={card}><div className="text-[10px] text-muted">{label}</div><div className="mt-1 font-mono text-xl text-foreground">{summary.data?.[key as keyof typeof summary.data] ?? '—'}</div></div>)}</div>
      <div className="rounded-card border border-warning/30 bg-warning/10 px-4 py-3 text-xs text-warning"><ShieldCheck className="mr-1 inline h-3.5 w-3.5" />安全边界：只能使用本地模拟快照和纸面账本；没有 Broker、QMT 或真实下单入口。</div>
      <div className="flex flex-wrap gap-1 border-b border-border/70 pb-2">{[
        ['overview', '闭环状态'], ['signals', '统一 Signal'], ['orders', '订单与成交'], ['positions', '持仓投影'], ['reviews', '每日复盘'], ['outbox', 'Outbox'],
      ].map(([value, label]) => <button key={value} onClick={() => setTab(value as Tab)} className={cn('rounded-btn px-3 py-1.5 text-xs cursor-pointer', tab === value ? 'bg-accent text-white' : 'text-secondary hover:bg-elevated')}>{label}</button>)}</div>
      {tab === 'overview' && <Overview orders={orders.data?.items ?? []} risk={risk.data?.items ?? []} fills={fills.data?.items ?? []} positions={positions.data?.items ?? []} />}
      {tab === 'signals' && <SignalsPanel items={signals.data?.items ?? []} onSaved={refresh} />}
      {tab === 'orders' && <OrdersPanel plans={plans.data?.items ?? []} items={orders.data?.items ?? []} onSaved={refresh} />}
      {tab === 'positions' && <PositionsPanel items={positions.data?.items ?? []} onSaved={refresh} />}
      {tab === 'reviews' && <ReviewsPanel items={reviews.data?.items ?? []} onSaved={refresh} />}
      {tab === 'outbox' && <OutboxPanel items={outbox.data?.items ?? []} onSaved={refresh} />}
    </div></div>
  </div>
}

function Overview({ orders, risk, fills, positions }: { orders: PaperOrder[]; risk: { status: string; reasons: { message: string }[] }[]; fills: { id: string }[]; positions: { symbol: string; quantity: number; available_quantity: number }[] }) {
  return <div className="grid gap-3 md:grid-cols-2">
    <section className={card}><h2 className="flex items-center gap-2 text-sm font-semibold"><ClipboardCheck className="h-4 w-4 text-accent" />执行链路</h2><div className="mt-4 space-y-3 text-xs text-secondary">{[['Signal', '统一来源和 provenance'], ['Decision Gate', '人工批准后才能进入风控'], ['Risk', risk[0]?.status === 'passed' ? '最近一次通过' : risk[0]?.status === 'rejected' ? risk[0]?.reasons?.[0]?.message ?? '最近一次拒绝' : '尚无检查'], ['OMS', `${orders.length} 个纸面订单`], ['Fill / Projection', `${fills.length} 个确认成交 · ${positions.length} 个持仓`]].map(([title, detail], i) => <div key={title} className="flex items-center gap-3"><div className="grid h-7 w-7 place-items-center rounded-full bg-accent/10 text-accent">{i < 2 ? <CheckCircle2 className="h-4 w-4" /> : <PackageCheck className="h-4 w-4" />}</div><div><div className="text-foreground">{title}</div><div className="text-[11px]">{detail}</div></div></div>)}</div></section>
    <section className={card}><h2 className="flex items-center gap-2 text-sm font-semibold"><CircleAlert className="h-4 w-4 text-warning" />运行提示</h2><p className="mt-4 text-xs leading-relaxed text-secondary">纸面订单必须关联已批准的 Trade Plan。风险检查缺少 FRESH 行情、连续竞价状态、合法价格或可卖持仓时会拒绝执行。持仓只消费 confirmed paper fill，不从订单日志临时计算。</p></section>
  </div>
}

function SignalsPanel({ items, onSaved }: { items: { id: string; symbol: string; as_of: string; source: string; action: string; kind: string; score?: number | null }[]; onSaved: () => void }) {
  const [form, setForm] = useState({ symbol: '', as_of: new Date().toISOString().slice(0, 10), source: 'manual', source_id: 'paper-ui', action: 'entry', kind: 'entry' })
  const mutation = useMutation({ mutationFn: () => api.paperSignalCreate({ ...form, symbol: form.symbol.trim().toUpperCase(), payload: { created_from: 'paper-ui' }, provenance: { ui: true }, idempotency_key: keyFor('signal') }), onSuccess: () => { setForm({ ...form, symbol: '' }); onSaved() } })
  return <Panel title="统一 Signal"><div className="grid gap-3 lg:grid-cols-[20rem_1fr]"><div className={cn(card, 'space-y-2')}><input className={input} placeholder="标的，如 000001.SZ" value={form.symbol} onChange={e => setForm({ ...form, symbol: e.target.value })} /><input className={input} type="date" value={form.as_of} onChange={e => setForm({ ...form, as_of: e.target.value })} /><select className={input} value={form.source} onChange={e => setForm({ ...form, source: e.target.value })}><option value="manual">手工</option><option value="strategy">策略</option><option value="indicator">指标</option><option value="custom">自定义</option><option value="monitor">监控</option></select><select className={input} value={form.kind} onChange={e => setForm({ ...form, kind: e.target.value })}><option value="entry">入场</option><option value="exit">出场</option><option value="observation">观察</option></select><input className={input} placeholder="动作，如 entry" value={form.action} onChange={e => setForm({ ...form, action: e.target.value })} /><button disabled={!form.symbol.trim() || mutation.isPending} onClick={() => mutation.mutate()} className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-3 py-2 text-xs text-white disabled:opacity-50 cursor-pointer"><Plus className="h-3.5 w-3.5" />写入 Signal</button></div><div className="space-y-2">{items.length === 0 ? <Empty text="暂无统一 Signal。" /> : items.map(item => <article key={item.id} className={card}><div className="flex items-center gap-2"><span className="font-mono text-sm">{item.symbol}</span><Badge text={item.kind} /><Badge text={item.source} /><span className="ml-auto text-[10px] text-muted">{item.as_of}</span></div><div className="mt-2 text-xs text-secondary">{item.action} · {item.id}</div></article>)}</div></div></Panel>
}

function OrdersPanel({ plans, items, onSaved }: { plans: TradingPlan[]; items: PaperOrder[]; onSaved: () => void }) {
  const [form, setForm] = useState({ plan_id: '', price: '', quantity: '', as_of: new Date().toISOString().slice(0, 10) })
  const snapshot = () => ({ as_of: form.as_of, market_session: { trading_day: true, is_continuous: true, phase: 'paper_simulation' }, data_quality: { status: 'FRESH', usable: true }, quote: { last_price: Number(form.price), prev_close: Number(form.price) } })
  const submit = useMutation({ mutationFn: () => api.paperOrderSubmit({ plan_id: form.plan_id, snapshot: snapshot(), idempotency_key: keyFor('order') }), onSuccess: onSaved })
  const fill = useMutation({ mutationFn: (order: PaperOrder) => api.paperFillSimulate(order.id, { quantity: order.quantity - order.filled_quantity, price: order.limit_price, trade_date: order.execution_date, idempotency_key: keyFor('fill') }), onSuccess: onSaved })
  const cancel = useMutation({ mutationFn: (order: PaperOrder) => api.paperOrderTransition(order.id, { status: 'cancelled', reason: '人工取消纸面订单', expected_revision: order.revision, idempotency_key: keyFor('cancel') }), onSuccess: onSaved })
  const selected = plans.find(p => p.id === form.plan_id)
  return <Panel title="订单与模拟成交"><div className="grid gap-3 lg:grid-cols-[20rem_1fr]"><div className={cn(card, 'space-y-2')}><select className={input} value={form.plan_id} onChange={e => { const p = plans.find(x => x.id === e.target.value); setForm({ ...form, plan_id: e.target.value, price: p?.entry_price ? String(p.entry_price) : '', quantity: p?.quantity ? String(p.quantity) : '' }) }}><option value="">选择 Trade Plan</option>{plans.map(p => <option key={p.id} value={p.id}>{p.symbol} · {p.status} · {p.id}</option>)}</select><input className={input} type="date" value={form.as_of} onChange={e => setForm({ ...form, as_of: e.target.value })} /><input className={input} type="number" placeholder="模拟成交价" value={form.price} onChange={e => setForm({ ...form, price: e.target.value })} /><input className={input} type="number" placeholder="数量" value={form.quantity} onChange={e => setForm({ ...form, quantity: e.target.value })} /><p className="text-[10px] text-muted">{selected ? `需先在交易研究页批准 ${selected.id} 的 Decision Gate` : '只允许已批准计划通过风控'}</p><button disabled={!form.plan_id || !form.price || !form.quantity || submit.isPending} onClick={() => submit.mutate()} className="inline-flex items-center gap-1.5 rounded-btn bg-accent px-3 py-2 text-xs text-white disabled:opacity-50 cursor-pointer"><Send className="h-3.5 w-3.5" />经过 Risk 提交</button></div><div className="space-y-2">{items.length === 0 ? <Empty text="暂无纸面订单。" /> : items.map(order => <article key={order.id} className={card}><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-sm">{order.symbol}</span><Badge text={order.status} /><span className="text-xs text-secondary">{order.side} {order.quantity}@{order.limit_price}</span><span className="ml-auto text-[10px] text-muted">{order.execution_date}</span></div><div className="mt-2 text-[11px] text-secondary">{order.id} · 已成交 {order.filled_quantity}/{order.quantity}</div>{(order.status === 'accepted' || order.status === 'partially_filled') && <div className="mt-2 flex gap-2"><button disabled={fill.isPending} onClick={() => fill.mutate(order)} className="rounded-btn border border-bull/30 px-2 py-1 text-[10px] text-bull hover:bg-bull/10 cursor-pointer">模拟全部成交</button><button disabled={cancel.isPending} onClick={() => cancel.mutate(order)} className="rounded-btn border border-bear/30 px-2 py-1 text-[10px] text-bear hover:bg-bear/10 cursor-pointer">取消订单</button></div>}</article>)}</div></div></Panel>
}

function PositionsPanel({ items, onSaved }: { items: { symbol: string; quantity: number; available_quantity: number; avg_cost: number; realized_pnl: number }[]; onSaved: () => void }) {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10))
  const settle = useMutation({ mutationFn: () => api.paperSettle(asOf), onSuccess: onSaved })
  return <Panel title="持仓 Projection"><div className="mb-3 flex flex-wrap items-center gap-2"><input className={cn(input, 'max-w-44')} type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /><button onClick={() => settle.mutate()} disabled={settle.isPending} className="rounded-btn border border-accent/30 px-3 py-2 text-xs text-accent hover:bg-accent/10 cursor-pointer">结算 T+1 可卖数量</button></div><div className="grid gap-2 sm:grid-cols-2">{items.length === 0 ? <Empty text="暂无确认成交后的持仓。" /> : items.map(p => <article key={p.symbol} className={card}><div className="flex items-center gap-2"><Layers3 className="h-4 w-4 text-accent" /><span className="font-mono text-sm">{p.symbol}</span><span className="ml-auto text-xs text-bull">{p.realized_pnl.toFixed(2)}</span></div><div className="mt-3 grid grid-cols-3 gap-2 text-xs text-secondary"><span>持仓 <b className="text-foreground">{p.quantity}</b></span><span>可卖 <b className="text-foreground">{p.available_quantity}</b></span><span>成本 <b className="text-foreground">{p.avg_cost.toFixed(2)}</b></span></div></article>)}</div></Panel>
}

function ReviewsPanel({ items, onSaved }: { items: Record<string, any>[]; onSaved: () => void }) {
  const [asOf, setAsOf] = useState(new Date().toISOString().slice(0, 10))
  const [summary, setSummary] = useState('')
  const mutation = useMutation({ mutationFn: () => api.paperReviewCreate({ as_of: asOf, summary, idempotency_key: keyFor('review') }), onSuccess: onSaved })
  return <Panel title="Daily Review 不可变快照"><div className={cn(card, 'mb-3 flex flex-wrap gap-2')}><input className={cn(input, 'max-w-44')} type="date" value={asOf} onChange={e => setAsOf(e.target.value)} /><input className={cn(input, 'min-w-56 flex-1')} placeholder="本日复盘摘要" value={summary} onChange={e => setSummary(e.target.value)} /><button onClick={() => mutation.mutate()} disabled={mutation.isPending} className="rounded-btn bg-accent px-3 py-2 text-xs text-white cursor-pointer">生成快照</button></div>{items.length === 0 ? <Empty text="暂无每日复盘快照。" /> : items.map(item => <article key={item.id} className={card}><div className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-bull" /><span className="font-mono text-sm">{item.as_of}</span><span className="text-xs text-secondary">{item.summary || '无摘要'}</span><span className="ml-auto text-[10px] text-muted">{item.id}</span></div><div className="mt-2 text-[11px] text-muted">快照包含 Signal、Risk、订单、成交和持仓投影。</div></article>)}</Panel>
}

function OutboxPanel({ items, onSaved }: { items: Record<string, any>[]; onSaved: () => void }) {
  const mutation = useMutation({ mutationFn: (id: string) => api.paperOutboxUpdate(id, { status: 'sent' }), onSuccess: onSaved })
  return <Panel title="Outbox / Crash Recovery"><p className="text-xs text-secondary">事件先以 pending 状态写入本地 Outbox，再由本地消费者确认 sent 或记录 failed。此页面不向外部渠道投递。</p><div className="mt-3 space-y-2">{items.length === 0 ? <Empty text="暂无 Outbox 事件。" /> : items.map(item => <article key={String(item.id)} className={card}><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs text-accent">{String(item.event_type)}</span><Badge text={String(item.status)} /><span className="text-[10px] text-muted">attempts {String(item.attempts)}</span><button disabled={item.status === 'sent' || mutation.isPending} onClick={() => mutation.mutate(String(item.id))} className="ml-auto rounded-btn border border-bull/30 px-2 py-1 text-[10px] text-bull hover:bg-bull/10 cursor-pointer">标记已处理</button></div><div className="mt-1 text-[10px] text-secondary">{String(item.entity_type)} · {String(item.entity_id)}</div></article>)}</div></Panel>
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) { return <section className="space-y-3"><h2 className="flex items-center gap-2 text-xs font-semibold text-foreground"><span className="h-3 w-0.5 rounded-full bg-accent" />{title}</h2>{children}</section> }
function Badge({ text }: { text: string }) { return <span className="rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] text-accent">{text}</span> }
function Empty({ text }: { text: string }) { return <div className="rounded-card border border-dashed border-border px-6 py-12 text-center text-xs text-muted">{text}</div> }
