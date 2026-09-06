import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Plug, RefreshCw, ShieldAlert, ShieldCheck, WifiOff } from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { api, type BrokerOrder } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

const card = 'rounded-card border border-border bg-surface/70 p-4 shadow-sm'
const input = 'w-full rounded-btn border border-border bg-base px-3 py-2 text-xs text-foreground outline-none focus:border-accent'

export function BrokerQmt() {
  const qc = useQueryClient()
  const [symbol, setSymbol] = useState('000001.SZ')
  const [price, setPrice] = useState('10')
  const [order, setOrder] = useState({ symbol: '000001.SZ', side: 'buy' as 'buy' | 'sell', quantity: '100', limit_price: '10' })
  const [confirmationId, setConfirmationId] = useState<string | null>(null)
  const [clientOrderId, setClientOrderId] = useState<string | null>(null)
  const status = useQuery({ queryKey: QK.brokerStatus, queryFn: api.brokerStatus })
  const orders = useQuery({ queryKey: QK.brokerOrders, queryFn: api.brokerOrders })
  const fills = useQuery({ queryKey: QK.brokerFills, queryFn: api.brokerFills })
  const account = useQuery({ queryKey: QK.brokerAccount, queryFn: api.brokerAccount })
  const refresh = () => {
    ;[QK.brokerStatus, QK.brokerOrders, QK.brokerFills, QK.brokerAccount, QK.brokerReconcile].forEach(key => qc.invalidateQueries({ queryKey: key }))
    qc.invalidateQueries({ queryKey: ['broker-quote'] })
  }
  const connect = useMutation({ mutationFn: () => api.brokerConnect({ adapter: 'mock', mode: 'HUMAN_CONFIRM' }), onSuccess: refresh })
  const mode = useMutation({ mutationFn: (value: 'HUMAN_CONFIRM' | 'LIVE_SHADOW') => api.brokerSetMode(value), onSuccess: refresh })
  const disconnect = useMutation({ mutationFn: api.brokerDisconnect, onSuccess: refresh })
  const kill = useMutation({ mutationFn: () => api.brokerSafetyKill('用户在 Broker 工作台手动触发'), onSuccess: refresh })
  const reset = useMutation({ mutationFn: api.brokerSafetyReset, onSuccess: refresh })
  const seed = useMutation({ mutationFn: () => api.brokerQuoteSeed({ symbol: symbol.trim().toUpperCase(), last_price: Number(price) }), onSuccess: refresh })
  const orderPayload = (id = clientOrderId ?? `broker-ui-${Date.now()}`) => ({
    client_order_id: id,
    symbol: order.symbol.trim().toUpperCase(),
    side: order.side,
    quantity: Number(order.quantity),
    limit_price: Number(order.limit_price),
    order_type: 'limit' as const,
    human_confirmed: false,
    metadata: { created_from: 'broker-ui' },
  })
  const requestConfirmation = useMutation({
    mutationFn: () => {
      const id = `broker-ui-${Date.now()}`
      setClientOrderId(id)
      return api.brokerConfirmationRequest({
        action: 'broker.submit_order',
        payload: orderPayload(id),
      })
    },
    onSuccess: result => setConfirmationId(String(result.id)),
  })
  const approveConfirmation = useMutation({
    mutationFn: () => api.brokerConfirmationDecision(confirmationId!, 'approved'),
    onSuccess: () => submit.mutate(),
  })
  const submit = useMutation({
    mutationFn: () => api.brokerOrderSubmit({ ...orderPayload(), confirmation_id: confirmationId ?? undefined }),
    onSuccess: () => {
      setConfirmationId(null)
      setClientOrderId(null)
      refresh()
    },
  })
  const reconcile = useMutation({ mutationFn: () => api.brokerReconcile(), onSuccess: refresh })
  const shadow = useMutation({
    mutationFn: () => api.brokerLiveShadow({
      ...orderPayload(),
      client_order_id: `shadow-ui-${Date.now()}`,
      simulate_fill: true,
    }),
    onSuccess: refresh,
  })
  const current = status.data

  return <div className="flex h-full min-h-0 flex-col">
    <PageHeader title="Broker / QMT 安全边界" subtitle="Protocol → Agent → Quote / Trade → Reconcile · 当前仅 mock，不连接真实 QMT" right={<button onClick={refresh} className="inline-flex items-center gap-1 rounded-btn border border-border px-2 py-1 text-[11px] text-secondary hover:bg-elevated cursor-pointer"><RefreshCw className="h-3 w-3" />刷新</button>} />
    <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4"><div className="mx-auto max-w-6xl space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Stat icon={current?.connection === 'connected' ? CheckCircle2 : WifiOff} label="连接" value={current?.connection ?? '—'} tone={current?.connection === 'connected' ? 'good' : 'warn'} />
        <Stat icon={Plug} label="适配器" value={current?.adapter ?? '—'} />
        <Stat icon={ShieldCheck} label="执行模式" value={current?.mode ?? '—'} />
        <Stat icon={current?.kill_switch ? ShieldAlert : ShieldCheck} label="安全门" value={current?.kill_switch ? 'KILL SWITCH' : '可用'} tone={current?.kill_switch ? 'bad' : 'good'} />
      </div>
      <div className="rounded-card border border-warning/30 bg-warning/10 px-4 py-3 text-xs text-warning"><ShieldCheck className="mr-1 inline h-3.5 w-3.5" />真实 QMT SDK、网络行情和真实下单均已关闭。HUMAN_CONFIRM 需要勾选人工确认，LIVE_SHADOW 只写入 mock 账本，AUTO 永久禁用。</div>
      <div className="grid gap-3 lg:grid-cols-2">
        <section className={card}><h2 className="text-sm font-semibold">连接与安全</h2><div className="mt-3 flex flex-wrap gap-2"><button onClick={() => connect.mutate()} disabled={connect.isPending || current?.connection === 'connected'} className="rounded-btn bg-accent px-3 py-2 text-xs text-white disabled:opacity-50 cursor-pointer">连接 Mock Broker</button><button onClick={() => disconnect.mutate()} disabled={disconnect.isPending || current?.connection !== 'connected'} className="rounded-btn border border-border px-3 py-2 text-xs text-secondary disabled:opacity-50 cursor-pointer">断开</button><button onClick={() => mode.mutate('HUMAN_CONFIRM')} disabled={mode.isPending || current?.mode === 'HUMAN_CONFIRM'} className="rounded-btn border border-warning/30 px-3 py-2 text-xs text-warning disabled:opacity-50 cursor-pointer">HUMAN_CONFIRM</button><button onClick={() => mode.mutate('LIVE_SHADOW')} disabled={mode.isPending || current?.mode === 'LIVE_SHADOW'} className="rounded-btn border border-accent/30 px-3 py-2 text-xs text-accent disabled:opacity-50 cursor-pointer">LIVE_SHADOW</button>{current?.kill_switch ? <button onClick={() => reset.mutate()} className="rounded-btn border border-bull/30 px-3 py-2 text-xs text-bull cursor-pointer">解除 Kill Switch</button> : <button onClick={() => kill.mutate()} className="rounded-btn border border-danger/30 px-3 py-2 text-xs text-danger cursor-pointer">触发 Kill Switch</button>}</div><div className="mt-3 grid grid-cols-2 gap-2 text-xs text-secondary"><span>Agent: <b className="text-foreground">{current?.agent?.transport ?? '—'}</b></span><span>隔离: <b className="text-foreground">{current?.agent?.isolated ? '是' : '—'}</b></span><span>SDK: <b className="text-foreground">{current?.sdk_configured ? '已配置' : '未配置'}</b></span><span>真实下单: <b className="text-foreground">{current?.real_order_enabled ? '开启' : '关闭'}</b></span></div>{current?.last_error && <p className="mt-3 text-[11px] text-warning">{current.last_error}</p>}</section>
        <section className={card}><h2 className="text-sm font-semibold">行情质量 / provenance</h2><div className="mt-3 flex gap-2"><input className={input} value={symbol} onChange={e => setSymbol(e.target.value)} placeholder="000001.SZ" /><input className={cn(input, 'max-w-32')} value={price} onChange={e => setPrice(e.target.value)} type="number" /><button onClick={() => seed.mutate()} disabled={seed.isPending} className="rounded-btn bg-accent px-3 py-2 text-xs text-white cursor-pointer">注入 Mock 行情</button></div><QuoteLine symbol={symbol} /></section>
      </div>
      <div className="grid gap-3 lg:grid-cols-[20rem_1fr]">
        <section className={cn(card, 'space-y-2')}><h2 className="text-sm font-semibold">安全交易测试</h2><input className={input} value={order.symbol} onChange={e => { setOrder({ ...order, symbol: e.target.value }); setConfirmationId(null); setClientOrderId(null) }} placeholder="标的" /><select className={input} value={order.side} onChange={e => { setOrder({ ...order, side: e.target.value as 'buy' | 'sell' }); setConfirmationId(null); setClientOrderId(null) }}><option value="buy">买入</option><option value="sell">卖出</option></select><input className={input} value={order.quantity} onChange={e => { setOrder({ ...order, quantity: e.target.value }); setConfirmationId(null); setClientOrderId(null) }} type="number" placeholder="数量" /><input className={input} value={order.limit_price} onChange={e => { setOrder({ ...order, limit_price: e.target.value }); setConfirmationId(null); setClientOrderId(null) }} type="number" placeholder="限价" /><button onClick={() => requestConfirmation.mutate()} disabled={requestConfirmation.isPending || current?.connection !== 'connected'} className="w-full rounded-btn border border-warning/30 px-3 py-2 text-xs text-warning disabled:opacity-50 cursor-pointer">1. 申请人工确认</button>{confirmationId && <div className="rounded-btn border border-warning/30 bg-warning/10 p-2 text-[10px] text-warning">确认请求 {confirmationId} 已创建。确认内容锁定后才能批准。</div>}<button onClick={() => approveConfirmation.mutate()} disabled={!confirmationId || approveConfirmation.isPending} className="w-full rounded-btn bg-accent px-3 py-2 text-xs text-white disabled:opacity-50 cursor-pointer">2. 批准并提交 Mock 订单</button><button onClick={() => shadow.mutate()} disabled={shadow.isPending || current?.connection !== 'connected' || current?.mode !== 'LIVE_SHADOW'} className="w-full rounded-btn border border-accent/30 px-3 py-2 text-xs text-accent disabled:opacity-50 cursor-pointer">LIVE_SHADOW 一键验收</button></section>
        <section className={card}><div className="flex items-center justify-between"><h2 className="text-sm font-semibold">Broker 订单</h2><button onClick={() => reconcile.mutate()} className="rounded-btn border border-border px-2 py-1 text-[11px] text-secondary cursor-pointer">执行对账</button></div><div className="mt-3 space-y-2">{(orders.data?.items ?? []).length === 0 ? <Empty text="暂无 Broker 订单。" /> : orders.data?.items.map(item => <OrderRow key={item.id} item={item} onRefresh={refresh} />)}</div><div className="mt-4 text-xs text-secondary">成交回报 {fills.data?.items.length ?? 0} 条 · 账户质量 {account.data?.quality ?? '—'} · 资产 {account.data?.equity?.toFixed(2) ?? '—'}</div></section>
      </div>
    </div></div>
  </div>
}

function QuoteLine({ symbol }: { symbol: string }) {
  const quote = useQuery({ queryKey: QK.brokerQuote(symbol), queryFn: () => api.brokerQuote(symbol), enabled: !!symbol.trim() })
  return <div className="mt-3 rounded-btn border border-border bg-base px-3 py-2 text-xs"><div className="flex items-center gap-2"><span className="font-mono text-foreground">{quote.data?.symbol ?? symbol.toUpperCase()}</span><Badge text={quote.data?.quality ?? '加载中'} tone={quote.data?.quality === 'FRESH' ? 'good' : 'warn'} /><span className="ml-auto text-secondary">{quote.data?.last_price ?? '—'}</span></div><div className="mt-1 text-[10px] text-muted">{quote.data?.reason ?? `来源 ${String(quote.data?.provenance?.adapter ?? '—')} · ${quote.data?.as_of || '—'}`}</div></div>
}

function OrderRow({ item, onRefresh }: { item: BrokerOrder; onRefresh: () => void }) {
  const cancel = useMutation({ mutationFn: () => api.brokerOrderCancel(item.id), onSuccess: onRefresh })
  const fill = useMutation({ mutationFn: () => api.brokerFillSimulate(item.id, { quantity: item.quantity - item.filled_quantity, price: item.limit_price }), onSuccess: onRefresh })
  return <article className="rounded-btn border border-border bg-base p-3 text-xs"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-foreground">{item.symbol}</span><Badge text={item.status} /><span className="text-secondary">{item.side} {item.quantity}@{item.limit_price}</span><span className="ml-auto text-[10px] text-muted">{item.client_order_id}</span></div>{(item.status === 'accepted' || item.status === 'partially_filled') && <div className="mt-2 flex gap-2"><button onClick={() => fill.mutate()} className="rounded-btn border border-bull/30 px-2 py-1 text-[10px] text-bull cursor-pointer">模拟成交</button><button onClick={() => cancel.mutate()} className="rounded-btn border border-bear/30 px-2 py-1 text-[10px] text-bear cursor-pointer">撤单</button></div>}</article>
}

function Stat({ icon: Icon, label, value, tone = 'normal' }: { icon: typeof Plug; label: string; value: string; tone?: 'normal' | 'good' | 'warn' | 'bad' }) { return <div className={cn(card, tone === 'bad' && 'border-danger/30', tone === 'warn' && 'border-warning/30', tone === 'good' && 'border-bull/30')}><div className="flex items-center gap-2 text-[10px] text-muted"><Icon className="h-3.5 w-3.5" />{label}</div><div className="mt-2 text-sm font-semibold text-foreground">{value}</div></div> }
function Badge({ text, tone = 'normal' }: { text: string; tone?: 'normal' | 'good' | 'warn' }) { return <span className={cn('rounded-full border px-2 py-0.5 text-[10px]', tone === 'good' ? 'border-bull/30 bg-bull/10 text-bull' : tone === 'warn' ? 'border-warning/30 bg-warning/10 text-warning' : 'border-accent/30 bg-accent/10 text-accent')}>{text}</span> }
function Empty({ text }: { text: string }) { return <div className="rounded-card border border-dashed border-border px-6 py-10 text-center text-xs text-muted">{text}</div> }
