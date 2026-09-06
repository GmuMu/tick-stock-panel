import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api, type StockBoxAnalysis, type StockBoxState } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

interface Props {
  symbol: string
  lookback?: number
  onLookbackChange?: (lookback: number) => void
}

const LOOKBACK_OPTIONS = [30, 60, 120] as const

function statusClass(status: StockBoxState['status']) {
  if (status === 'breakout_up') return 'border-bull/30 bg-bull/10 text-bull'
  if (status === 'breakout_down') return 'border-bear/30 bg-bear/10 text-bear'
  if (status === 'near_upper') return 'border-warning/30 bg-warning/10 text-warning'
  if (status === 'near_lower') return 'border-accent/30 bg-accent/10 text-accent'
  return 'border-border bg-elevated text-secondary'
}

function pct(value: number | null | undefined) {
  return value == null ? '--' : `${value.toFixed(2)}%`
}

function price(value: number | null | undefined) {
  return value == null ? '--' : value.toFixed(2)
}

export function StockBoxAnalysis({ symbol, lookback: controlledLookback, onLookbackChange }: Props) {
  const [localLookback, setLocalLookback] = useState<number>(60)
  const lookback = controlledLookback ?? localLookback
  const query = useQuery({
    queryKey: QK.stockBox(symbol, lookback),
    queryFn: () => api.stockAnalysisBox(symbol, lookback),
    enabled: !!symbol,
    staleTime: 30_000,
  })

  const data = query.data
  return (
    <section className="mt-4 rounded-card border border-border bg-surface/70 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">箱体分析</h3>
          <p className="mt-0.5 text-[11px] text-muted">基于前复权日K，判断当前价格在箱体中的位置和突破状态</p>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="inline-flex rounded border border-border bg-elevated p-0.5">
            {LOOKBACK_OPTIONS.map(option => (
              <button
                key={option}
                type="button"
                onClick={() => {
                  onLookbackChange?.(option)
                  if (!onLookbackChange) setLocalLookback(option)
                }}
                className={cn(
                  'rounded px-2 py-1 text-[10px] font-mono transition-colors',
                  lookback === option ? 'bg-accent/20 text-accent' : 'text-muted hover:text-secondary',
                )}
              >
                {option}日
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="rounded-btn p-1.5 text-secondary transition-colors hover:bg-elevated hover:text-foreground"
            title="刷新箱体分析"
            aria-label="刷新箱体分析"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {query.isLoading && <div className="py-5 text-center text-xs text-muted">正在计算箱体...</div>}
      {query.isError && <div className="py-5 text-center text-xs text-danger">箱体分析加载失败，请稍后重试</div>}
      {!query.isLoading && !query.isError && data && !data.box && (
        <div className="py-5 text-center text-xs text-muted">{data.message}</div>
      )}

      {data?.box && data.current && data.volume && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
            <Metric label="当前价格" value={price(data.current.close)} />
            <Metric label="箱体上沿" value={price(data.box.upper)} tone="text-warning" />
            <Metric label="箱体下沿" value={price(data.box.lower)} tone="text-accent" />
            <Metric label="箱体宽度" value={pct(data.box.width_pct)} />
            <Metric label="分析评分" value={`${data.score ?? '--'}`} tone="text-foreground" />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_1fr]">
            <div>
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-muted">箱体当前位置</span>
                <span className="font-mono text-secondary">{pct(data.box.position_pct)}</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-elevated">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-accent via-warning to-danger transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, data.box.position_pct ?? 0))}%` }}
                />
              </div>
              <div className="mt-1 flex justify-between text-[10px] text-muted">
                <span>下沿 {price(data.box.lower)}</span>
                <span>中轴 {price(data.box.middle)}</span>
                <span>上沿 {price(data.box.upper)}</span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <Metric label="状态" value={data.box.status_label} tone={
                data.box.status === 'breakout_up'
                  ? 'text-bull'
                  : data.box.status === 'breakout_down'
                    ? 'text-bear'
                    : data.box.status === 'near_upper'
                      ? 'text-warning'
                      : 'text-secondary'
              } />
              <Metric label="量比" value={data.volume.ratio == null ? '--' : `${data.volume.ratio.toFixed(2)}x`} tone={data.volume.confirmed ? 'text-bull' : 'text-muted'} />
              <Metric label="MA20" value={price(data.current.ma20)} />
              <Metric label="数据日期" value={data.as_of ?? '--'} />
            </div>
          </div>

          <div className="mt-4 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
            {data.conditions.map(condition => (
              <div key={condition.key} className="rounded border border-border/70 bg-base/40 px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] text-secondary">{condition.label}</span>
                  <span className={condition.passed ? 'text-bull' : 'text-muted'}>{condition.passed ? '通过' : '未通过'}</span>
                </div>
                <div className="mt-1 text-[10px] text-muted">{condition.detail}</div>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-1.5 border-t border-border/70 pt-3">
            <span className="mr-1 text-[10px] text-muted">近期状态</span>
            {data.recent.map(item => (
              <span
                key={`${item.date}-${item.status}`}
                className={cn('rounded border px-1.5 py-0.5 text-[10px]', statusClass(item.status))}
                title={`${item.date} · ${price(item.close)}`}
              >
                {item.date.slice(5)} {item.status_label}
              </span>
            ))}
          </div>
          <p className="mt-3 text-[10px] text-muted">{data.message}</p>
        </>
      )}
    </section>
  )
}

function Metric({ label, value, tone = 'text-foreground' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border/70 bg-base/40 px-2.5 py-2">
      <div className="text-[10px] text-muted">{label}</div>
      <div className={cn('mt-1 truncate font-mono text-sm', tone)}>{value}</div>
    </div>
  )
}
