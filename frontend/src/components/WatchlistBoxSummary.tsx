import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { api, type StockBoxAnalysis, type StockBoxState } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'

interface Props {
  symbols: string[]
  names: Record<string, string>
  onPreview: (symbol: string, name: string) => void
}

const LOOKBACK_OPTIONS = [30, 60, 120] as const

function statusClass(status: StockBoxState['status']) {
  if (status === 'breakout_up') return 'border-bull/30 bg-bull/10 text-bull'
  if (status === 'breakout_down') return 'border-bear/30 bg-bear/10 text-bear'
  if (status === 'near_upper') return 'border-warning/30 bg-warning/10 text-warning'
  if (status === 'near_lower') return 'border-accent/30 bg-accent/10 text-accent'
  return 'border-border bg-elevated text-secondary'
}

function BoxTag({
  item,
  onClick,
}: {
  item: StockBoxAnalysis
  onClick: () => void
}) {
  const box = item.box
  if (!box) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-2 rounded border px-2.5 py-1.5 text-left transition-colors hover:border-accent/50',
        statusClass(box.status),
      )}
      title={`${item.symbol} · ${box.status_label}`}
    >
      <span className="font-mono text-[11px]">{item.symbol}</span>
      <span className="text-[10px]">{box.status_label}</span>
      <span className="font-mono text-[10px] opacity-80">{box.position_pct?.toFixed(0) ?? '--'}%</span>
    </button>
  )
}

export function WatchlistBoxSummary({ symbols, names, onPreview }: Props) {
  const [lookback, setLookback] = useState<number>(60)
  const symbolsKey = symbols.join(',')
  const query = useQuery({
    queryKey: QK.stockBoxBatch(symbolsKey, lookback),
    queryFn: () => api.stockAnalysisBoxBatch(symbols, lookback),
    enabled: symbols.length > 0,
    staleTime: 60_000,
  })
  const results = query.data?.results ?? {}
  const analyzed = Object.values(results).filter(item => item.box)
  const counts = useMemo(() => ({
    breakoutUp: analyzed.filter(item => item.box?.status === 'breakout_up').length,
    nearUpper: analyzed.filter(item => item.box?.status === 'near_upper').length,
    inside: analyzed.filter(item => item.box?.status === 'inside').length,
    nearLower: analyzed.filter(item => item.box?.status === 'near_lower' || item.box?.status === 'breakout_down').length,
  }), [analyzed])

  return (
    <section className="border-b border-border bg-surface/70 px-5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-foreground">自选股箱体观察</h3>
          <p className="mt-0.5 text-[11px] text-muted">
            已分析 {analyzed.length}/{symbols.length} 只，点击状态可打开个股箱体详情
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="inline-flex rounded border border-border bg-elevated p-0.5">
            {LOOKBACK_OPTIONS.map(option => (
              <button
                key={option}
                type="button"
                onClick={() => setLookback(option)}
                className={cn(
                  'rounded px-2 py-1 text-[10px] font-mono',
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
            disabled={query.isFetching || symbols.length === 0}
            className="rounded-btn p-1.5 text-secondary transition-colors hover:bg-elevated hover:text-foreground disabled:opacity-40"
            title="刷新箱体观察"
            aria-label="刷新箱体观察"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', query.isFetching && 'animate-spin')} />
          </button>
        </div>
      </div>

      {query.isLoading && <div className="py-4 text-xs text-muted">正在批量计算箱体...</div>}
      {query.isError && <div className="py-4 text-xs text-danger">批量箱体分析失败，请刷新重试</div>}
      {!query.isLoading && !query.isError && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <SummaryMetric label="向上突破" value={counts.breakoutUp} tone="text-bull" />
            <SummaryMetric label="接近上沿" value={counts.nearUpper} tone="text-warning" />
            <SummaryMetric label="箱体运行" value={counts.inside} tone="text-secondary" />
            <SummaryMetric label="下沿风险" value={counts.nearLower} tone="text-bear" />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {analyzed
              .filter(item => item.box?.status === 'breakout_up' || item.box?.status === 'near_upper' || item.box?.status === 'breakout_down')
              .sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
              .slice(0, 20)
              .map(item => (
                <BoxTag
                  key={item.symbol}
                  item={item}
                  onClick={() => onPreview(item.symbol, names[item.symbol] ?? '')}
                />
              ))}
            {analyzed.length === 0 && <span className="text-[11px] text-muted">暂无足够日K数据</span>}
          </div>
        </>
      )}
    </section>
  )
}

function SummaryMetric({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded border border-border/70 bg-base/40 px-2.5 py-2">
      <div className="text-[10px] text-muted">{label}</div>
      <div className={cn('mt-1 font-mono text-base', tone)}>{value}</div>
    </div>
  )
}
