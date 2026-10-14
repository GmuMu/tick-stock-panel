import { useEffect, useRef, useMemo, useState } from 'react'
import { chartTheme, getTheme, useTheme } from '@/lib/theme'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import type { KlineRow, LevelSeries, StockChanAnalysis } from '@/lib/api'

/**
 * 个股分析专用日 K 图表。
 *
 * 与 StockDailyKChart/EChartsCandlestick 刻意不复用:
 *   - 那套图表面向「行情浏览」,强调全套指标副图(MA/MACD/KDJ/BOLL)、涨停标记等;
 *   - 本图表面向「分析决策」,核心是【关键价位】(压力/支撑/密集区/枢轴/前高前低),
 *     通过开关按钮控制各价位组的显隐,布局更简洁(主图 + 成交量即可)。
 *
 * 预留接口(类型已定义,渲染逻辑留 hook,后续实现):
 *   - markers: 日期标记点(新闻/暴雷/利好 → markPoint)
 *   - ranges:  区间高亮(事件区间 → markArea)
 *   - onDateClick: 点击日期回调(后续接消息面时间轴)
 *   - 指标副图: MACD/RSI/KDJ 按独立 pane 渲染,避免把振荡指标压到价格轴
 */

// ===== 配色(红涨绿跌, 双主题通用); 画布轴/网格主题相关色走 CT() =====
const THEME = {
  bull: '#C74040',
  bear: '#2D9B65',
  volUp: 'rgba(240,68,56,0.5)',
  volDown: 'rgba(18,183,106,0.5)',
}

/** 当前主题的图表调色板 (buildOption 渲染时调用; 切换由组件 effect 触发重建)。 */
const CT = () => chartTheme(getTheme())

// ===== 价位类型(与后端 levels.py 的 LEVEL_TYPES 对齐) =====
export type LevelType = 'sr' | 'pivot' | 'extreme' | 'boll' | 'keltner_s' | 'keltner_m' | 'keltner_l' | 'atr_stop' | 'gap' | 'fib' | 'round'

export interface PriceLevel {
  value: number
  label: string
  type: LevelType
  side: 'resistance' | 'support' | 'neutral'
  strength?: 'strong' | 'medium' | 'weak'
  /** 档位(仅 pivot 有):0=P, 1=R1/S1, 2=R2/S2, 3=R3/S3 */
  rank?: number
}

/** 价位组开关配置:label = 按钮文案,color = markLine 颜色 */
export const LEVEL_GROUPS: { key: LevelType; label: string; color: string }[] = [
  { key: 'sr',       label: '压力支撑',  color: '#F97316' },   // 橙(成交密集区,价量驱动)
  { key: 'pivot',    label: '枢轴点',    color: '#8B5CF6' },   // 紫
  { key: 'extreme',  label: '前高前低',  color: '#EAB308' },   // 黄
  { key: 'boll',     label: '布林带',    color: '#F97316' },   // 橙(MA20±2σ 曲线)
  { key: 'keltner_s',label: 'Keltner短期',  color: '#06B6D4' },   // 青(MA20±2ATR 曲线)
  { key: 'keltner_m',label: 'Keltner中期',  color: '#22D3EE' },   // 浅青(MA60±2.5ATR 曲线)
  { key: 'keltner_l',label: 'Keltner长期',  color: '#67E8F9' },   // 更浅青(MA120±3ATR 曲线)
  { key: 'atr_stop', label: 'ATR波动通道',  color: '#EF4444' },   // 红(警示)
  { key: 'gap',      label: '缺口位',    color: '#EC4899' },   // 粉
  { key: 'fib',      label: '斐波那契',  color: '#F59E0B' },   // 金
  { key: 'round',    label: '整数关口',  color: '#71717A' },   // 灰(心理位,弱视觉)
]

// 通道曲线元数据(单一数据源):供 buildOption 画线 + 右侧面板取最新值共用。
//   alignedKey: alignedSeries 中的 key(由 series.boll/keltner/atr 对齐而来)
//   group:      属于哪个价位开关组(开关该组即开关这条曲线)
//   endLabel:   右侧端点标签(显示最新值的文字)
const CURVE_DEFS: { alignedKey: string; group: LevelType; endLabel: string; color: string; dashed?: boolean }[] = [
  { alignedKey: 'boll_upper',     group: 'boll',      endLabel: '布林上轨', color: '#F97316', dashed: true },
  { alignedKey: 'boll_lower',     group: 'boll',      endLabel: '布林下轨', color: '#F97316', dashed: true },
  { alignedKey: 'boll_mid',       group: 'boll',      endLabel: '布林中轨', color: '#FB923C', dashed: false },
  { alignedKey: 'keltner_s_upper',group: 'keltner_s', endLabel: 'Keltner短上', color: '#06B6D4', dashed: true },
  { alignedKey: 'keltner_s_lower',group: 'keltner_s', endLabel: 'Keltner短下', color: '#06B6D4', dashed: true },
  { alignedKey: 'keltner_m_upper',group: 'keltner_m', endLabel: 'Keltner中上', color: '#22D3EE', dashed: true },
  { alignedKey: 'keltner_m_lower',group: 'keltner_m', endLabel: 'Keltner中下', color: '#22D3EE', dashed: true },
  { alignedKey: 'keltner_l_upper',group: 'keltner_l', endLabel: 'Keltner长上', color: '#67E8F9', dashed: true },
  { alignedKey: 'keltner_l_lower',group: 'keltner_l', endLabel: 'Keltner长下', color: '#67E8F9', dashed: true },
  { alignedKey: 'atr_stop',       group: 'atr_stop',  endLabel: 'ATR下轨', color: '#EF4444', dashed: true },
  { alignedKey: 'atr_tp',         group: 'atr_stop',  endLabel: 'ATR上轨', color: '#F87171', dashed: true },
]

type ChanLayer = 'fractal' | 'bi' | 'segment' | 'zone' | 'point' | 'cbsp' | 'eigen' | 'trendline' | 'ma' | 'channel' | 'signal' | 'segmentSignal' | 'segzs' | 'multilevel' | 'nesting' | 'demark' | 'macd' | 'rsi' | 'kdj' | 'wyckoff'

const CHAN_LAYER_GROUPS: { key: ChanLayer; label: string; color: string }[] = [
  { key: 'fractal',   label: '分型',     color: '#F59E0B' },
  { key: 'segment',   label: '线段',     color: '#A78BFA' },
  { key: 'bi',        label: '笔',       color: '#38BDF8' },
  { key: 'zone',      label: '中枢',     color: '#0EA5E9' },
  { key: 'point',     label: 'B/S点',    color: '#22C55E' },
  { key: 'cbsp',      label: '严格CBSP', color: '#22D3EE' },
  { key: 'eigen',     label: '特征序列', color: '#F97316' },
  { key: 'trendline', label: '趋势线',   color: '#E879F9' },
  { key: 'ma',        label: '均线',     color: '#FACC15' },
  { key: 'channel',   label: '通道',     color: '#06B6D4' },
  { key: 'signal',    label: '辅助信号', color: '#FB7185' },
  { key: 'segmentSignal', label: '线段信号', color: '#F97316' },
  { key: 'segzs',     label: '线段中枢', color: '#14B8A6' },
  { key: 'multilevel', label: '多级别中枢', color: '#C084FC' },
  { key: 'nesting',   label: '区间套',   color: '#FDE047' },
  { key: 'demark',   label: 'TD信号',   color: '#F43F5E' },
  { key: 'macd',      label: 'MACD',     color: '#60A5FA' },
  { key: 'rsi',       label: 'RSI',      color: '#F59E0B' },
  { key: 'kdj',       label: 'KDJ',      color: '#A78BFA' },
  { key: 'wyckoff',   label: '威科夫',   color: '#34D399' },
]

type ExplanationSelection =
  | { kind: 'level'; key: LevelType }
  | { kind: 'chan'; key: ChanLayer | 'all' }

const LEVEL_EXPLANATIONS: Record<LevelType, { summary: string; usage: string }> = {
  sr: {
    summary: '基于历史成交密集区提取的压力与支撑价位。',
    usage: '价格接近支撑位时观察承接，接近压力位时观察放量突破；价位本身不是单独的买卖指令。',
  },
  pivot: {
    summary: '以前一交易日高低收计算的枢轴 P、R1-R3 和 S1-S3。',
    usage: 'P 反映日内多空分界，R/S 作为潜在压力与支撑，档位越远越适合做趋势目标而非短线确认。',
  },
  extreme: {
    summary: '近期窗口内的前高和前低，用于识别突破与回踩位置。',
    usage: '突破前高要结合成交量和收盘确认，跌破前低则重点观察是否形成趋势延续。',
  },
  boll: {
    summary: '布林上轨、中轨和下轨，反映价格相对波动区间的位置。',
    usage: '沿上轨运行不等于立即卖出，缩口后的放量突破比单次触碰轨道更有参考价值。',
  },
  keltner_s: {
    summary: '以 MA20 和 ATR 构成的短期 Keltner 通道。',
    usage: '适合判断短线趋势和波动扩张，价格脱离通道后要观察是否快速回归。',
  },
  keltner_m: {
    summary: '以 MA60 和 ATR 构成的中期 Keltner 通道。',
    usage: '用于确认中期趋势方向，价格站在中轨上方且通道抬升时趋势更健康。',
  },
  keltner_l: {
    summary: '以 MA120 和 ATR 构成的长期 Keltner 通道。',
    usage: '用于观察长期趋势边界，不能用来替代短线入场点。',
  },
  atr_stop: {
    summary: '根据 ATR 波动幅度动态计算的止损和止盈参考线。',
    usage: '线位会随波动变化，适合作为风险边界参考，不应在未确认仓位和交易周期前机械使用。',
  },
  gap: {
    summary: '历史跳空缺口形成的潜在回补、支撑或压力区域。',
    usage: '缺口是否有效要结合方向、成交量和后续收盘，不能仅因价格触及缺口就判断回补。',
  },
  fib: {
    summary: '根据关键波段高低点计算的斐波那契回撤和扩展位置。',
    usage: '把它当作潜在共振价位，最好与中枢、均线或前高前低叠加使用。',
  },
  round: {
    summary: '整数价位形成的心理关口。',
    usage: '整数位常产生挂单和止盈行为，参考强度较弱，需要其他结构信号确认。',
  },
}

const CHAN_LAYER_EXPLANATIONS: Record<ChanLayer, { summary: string; usage: string }> = {
  fractal: {
    summary: '由相邻 K 线的包含关系和局部高低点识别顶分型、底分型。',
    usage: '分型是结构拐点候选，不代表立即反转；需要后续成笔确认。',
  },
  bi: {
    summary: '连接交替顶底分型的有效波段，是缠论结构的基础单位。',
    usage: '向上笔和向下笔用于观察力度、节奏和背驰，最后未完成的波段不应提前当作确认信号。',
  },
  segment: {
    summary: '由多笔走势组合成的更高一级方向结构。',
    usage: '看线段方向和终点是否突破前一结构，适合判断趋势级别，不宜与单根 K 线混用。',
  },
  zone: {
    summary: '由笔的重叠区间形成的笔级中枢，显示多空反复交易的价格带。',
    usage: '中枢上沿、下沿和离开方向是观察三买三卖及趋势延续的关键。',
  },
  point: {
    summary: '基于当前笔与中枢关系生成的一买、二买、三买及对应卖点。',
    usage: 'B/S 点是研究辅助信号，必须结合级别、成交量和风险边界，不能直接等同自动下单。',
  },
  cbsp: {
    summary: '严格 CBSP 买卖点，要求结构确认、动能条件和中枢关系同时满足。',
    usage: '相比普通 B/S 点数量更少、确认更晚；只将已完成的笔和中枢纳入判断，适合做二次复核。',
  },
  eigen: {
    summary: '展示连续三笔构成的特征序列和是否存在重叠缺口。',
    usage: '重叠更偏向震荡延续，出现缺口时重点观察结构是否发生转折。',
  },
  trendline: {
    summary: '连接最近同类顶分型或底分型的阻力线、支撑线。',
    usage: '趋势线需要至少两个结构点确认，突破后还要观察收盘和回踩有效性。',
  },
  ma: {
    summary: '主图叠加 MA5、MA10、MA20、MA30、MA60 和 MA120。',
    usage: '均线用于观察趋势方向和多空排列，短周期交叉容易反复，不能单独作为买卖依据。',
  },
  channel: {
    summary: '缠论分析独立计算的 20 日高低通道及上下突破信号。',
    usage: '通道突破要结合收盘位置和量能，假突破通常会重新回到通道内部。',
  },
  signal: {
    summary: '汇总 MACD 交叉、通道突破和背驰等辅助研究信号。',
    usage: '该层用于快速发现值得复核的日期，具体信号已拆分到对应图层查看。',
  },
  segmentSignal: {
    summary: '根据相邻线段终点关系生成的线段级突破和转折提示。',
    usage: '它比笔级信号更慢、更偏趋势确认，适合和线段方向及线段中枢一起判断。',
  },
  wyckoff: {
    summary: '根据日线 OHLCV 规则识别威科夫候选事件：SC、Spring、SOS、UTAD 和 SOW。',
    usage: '这是量价启发式标注，不等同完整阶段判读；优先观察 Spring 后的放量 SOS，事件需要结合更长周期结构复核。',
  },
  segzs: {
    summary: '由三条线段重叠计算的线段级中枢，级别高于笔级中枢。',
    usage: '用于观察更大级别的震荡区间和离开方向，数据不足时不会强行绘制。',
  },
  multilevel: {
    summary: '把周线、月线等高级别中枢叠加到当前日线图上。',
    usage: '高级别中枢用于确定大方向和主要交易区间，低级别信号最好顺着高级别方向使用。',
  },
  nesting: {
    summary: '区间套把日线 CBSP 放入已完成的周线/月线中枢，显示级别共振情况。',
    usage: '黄色标记表示低级别信号落在高级别中枢内；方向一致时共振更强，仍需结合风险控制。',
  },
  demark: {
    summary: 'TD/Demark 计数和 TDST 支撑压力线，显示 9/13 趋势衰竭研究节点。',
    usage: '9/13 是衰竭提示而不是反转保证，必须配合价格结构和后续确认。',
  },
  macd: {
    summary: 'MACD DIF、DEA 和柱体副图，显示动能方向及金叉死叉。',
    usage: '柱体缩短只能说明动能变化，背驰判断要结合价格创新高低和缠论结构。',
  },
  rsi: {
    summary: 'RSI14 副图，标出 30、50、70 三条参考阈值。',
    usage: '超买超卖在强趋势中可能持续，优先观察 50 轴方向和价格结构，而不是见阈值就反向交易。',
  },
  kdj: {
    summary: 'KDJ(9,3,3) 副图，展示 K、D、J 三条动量曲线及金叉死叉。',
    usage: 'KDJ 对震荡行情更敏感，强趋势中容易钝化，建议与中枢和均线方向叠加确认。',
  },
}

// ===== 预留:标记 / 区间(后续新闻面、事件区间用) =====
export interface ChartMarker {
  date: string
  label?: string
  color?: string
  above?: boolean
}
export interface ChartRange {
  start: string
  end: string
  label?: string
  color?: string
}

interface Props {
  rows: KlineRow[]
  levels?: Record<LevelType, PriceLevel[]>
  /** 带状曲线指标(布林带/Keltner/ATR)的每日序列 —— 画成跟随时间漂移的曲线 */
  series?: LevelSeries
  /** series 数据对应的日期数组(与 series 各数组对齐) */
  seriesDates?: string[]
  /** 缠论结构图层(分型/笔/线段/中枢/确认买卖点) */
  chan?: StockChanAnalysis
  /** 默认开启的缠论图层;不传则显示完整结构和辅助指标 */
  defaultChanLayers?: ChanLayer[]
  /** 默认开启的价位组 */
  defaultLevelTypes?: LevelType[]
  /** 预留:新闻/暴雷/利好日期标记 */
  markers?: ChartMarker[]
  /** 预留:事件区间高亮 */
  ranges?: ChartRange[]
  /** 预留:点击某根 K 线 */
  onDateClick?: (date: string) => void
  height?: number
  className?: string
}

const VOL_PANE_H = 90

export function AnalysisKChart({
  rows,
  levels,
  series,
  seriesDates,
  chan,
  defaultChanLayers = ['fractal', 'segment', 'cbsp', 'trendline', 'channel', 'signal', 'segmentSignal'],
  defaultLevelTypes = ['sr', 'pivot', 'keltner_s'],
  markers,
  ranges,
  onDateClick,
  height = 460,
  className,
}: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstRef = useRef<ECharts | null>(null)
  /** seriesIndex → levelKey 映射, buildOption 填充, ECharts hover 事件反查 */
  const seriesKeyMapRef = useRef<Map<number, string>>(new Map())
  // 主题: buildOption 内部用 CT() 动态取色, 这里只负责切换时触发重建
  const theme = useTheme()
  const [activeTypes, setActiveTypes] = useState<Set<LevelType>>(new Set(defaultLevelTypes))
  /** 枢轴点显示到第几档:1=只P+R1/S1, 2=到R2/S2, 3=全档(R3/S3) */
  const [pivotRank, setPivotRank] = useState<1 | 2 | 3>(1)
  const [showChan, setShowChan] = useState(true)
  const [activeChanLayers, setActiveChanLayers] = useState<Set<ChanLayer>>(new Set(defaultChanLayers))
  /** 双向联动高亮: hover 价位标签 ↔ hover 下方文字行。值为 levelKey, null=无高亮 */
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  const [explanationSelection, setExplanationSelection] = useState<ExplanationSelection | null>(null)
  const wyckoffEvents = useMemo(() => buildWyckoffEvents(rows), [rows])

  // 数据预处理 + 带状曲线序列对齐(后端 series 的日期范围可能与 rows 不同,需映射)
  const { dates, candle, vols, dateIndex, zoomStart, alignedSeries } = useMemo(() => {
    const dates = rows.map(r => (typeof r.date === 'string' ? r.date.slice(0, 10) : String(r.date)))
    const candle = rows.map(r => [r.open, r.close, r.low, r.high])
    const vols = rows.map(r => ({
      value: r.volume ?? 0,
      itemStyle: { color: r.close >= r.open ? THEME.volUp : THEME.volDown },
    }))
    const dateIndex = new Map(dates.map((d, i) => [d, i]))
    // 默认显示最近 6 个月 ≈ 120 个交易日;数据不足则全部显示
    const showBars = 120
    const zoomStart = dates.length > showBars ? Math.round((1 - showBars / dates.length) * 100) : 0

    // 把后端 series(按 seriesDates 对齐)映射到前端 rows 的 dates 顺序
    const alignedSeries: Record<string, (number | null)[]> = {}
    if (series && seriesDates && seriesDates.length > 0) {
      // 构建 seriesDates 索引
      const sIdx = new Map(seriesDates.map((d, i) => [d, i]))
      // 通用对齐:给定 series 里某条数组,返回与 rows dates 对齐的版本
      const align = (arr: (number | null)[] | undefined): (number | null)[] => {
        if (!arr) return dates.map(() => null)
        return dates.map(d => {
          const i = sIdx.get(d)
          return i != null ? arr[i] : null
        })
      }
      if (series.boll) {
        alignedSeries['boll_upper'] = align(series.boll.upper)
        alignedSeries['boll_lower'] = align(series.boll.lower)
        if (series.boll.mid) alignedSeries['boll_mid'] = align(series.boll.mid)
      }
      if (series.keltner_s) {
        alignedSeries['keltner_s_upper'] = align(series.keltner_s.upper)
        alignedSeries['keltner_s_lower'] = align(series.keltner_s.lower)
      }
      if (series.keltner_m) {
        alignedSeries['keltner_m_upper'] = align(series.keltner_m.upper)
        alignedSeries['keltner_m_lower'] = align(series.keltner_m.lower)
      }
      if (series.keltner_l) {
        alignedSeries['keltner_l_upper'] = align(series.keltner_l.upper)
        alignedSeries['keltner_l_lower'] = align(series.keltner_l.lower)
      }
      if (series.atr) {
        alignedSeries['atr_stop'] = align(series.atr.stop_loss)
        alignedSeries['atr_tp'] = align(series.atr.take_profit)
      }
    }

    return { dates, candle, vols, dateIndex, zoomStart, alignedSeries }
  }, [rows, series, seriesDates])

  // 构建 option
  const buildOption = (): EChartsOption => {
    const priceLines = collectPriceLines(levels, activeTypes, pivotRank)
    const chanMarkPoints: any[] = []
    const chanMarkAreas: any[] = []
    const layerEnabled = (layer: ChanLayer) => Boolean(chan && showChan && activeChanLayers.has(layer))
    const showMacd = layerEnabled('macd')
    const showRsi = layerEnabled('rsi')
    const showKdj = layerEnabled('kdj')

    if (chan && showChan) {
      if (layerEnabled('fractal')) for (const fractal of chan.fractals ?? []) {
        if (!dateIndex.has(fractal.date)) continue
        chanMarkPoints.push({
          coord: [fractal.date, fractal.price],
          symbol: fractal.type === 'top' ? 'triangle' : 'triangle',
          symbolRotate: fractal.type === 'top' ? 180 : 0,
          symbolSize: 9,
          itemStyle: { color: fractal.type === 'top' ? '#F59E0B' : '#22C55E' },
          label: {
            show: true,
            formatter: fractal.type === 'top' ? '顶' : '底',
            color: fractal.type === 'top' ? '#F59E0B' : '#22C55E',
            fontSize: 9,
            position: fractal.type === 'top' ? 'top' : 'bottom',
          },
        })
      }
      if (layerEnabled('point')) for (const point of chan.points ?? []) {
        if (!dateIndex.has(point.date)) continue
        const isBuy = point.side === 'buy'
        chanMarkPoints.push({
          coord: [point.date, point.price],
          symbol: isBuy ? 'pin' : 'pin',
          symbolRotate: isBuy ? 0 : 180,
          symbolSize: 26,
          itemStyle: { color: isBuy ? '#16A34A' : '#DC2626' },
          label: {
            show: true,
            formatter: point.label,
            color: '#fff',
            fontSize: 9,
            fontWeight: 'bold',
          },
        })
      }
      if (layerEnabled('cbsp')) for (const point of chan.cbsp_points ?? []) {
        if (!dateIndex.has(point.date) || !Number.isFinite(point.price)) continue
        const isBuy = point.side === 'buy'
        chanMarkPoints.push({
          coord: [point.date, point.price],
          symbol: 'pin',
          symbolRotate: isBuy ? 0 : 180,
          symbolSize: 29,
          itemStyle: {
            color: isBuy ? '#0891B2' : '#0E7490',
            borderColor: '#ECFEFF',
            borderWidth: 1,
          },
          label: {
            show: true,
            formatter: point.label,
            color: '#ECFEFF',
            fontSize: 8,
            fontWeight: 'bold',
          },
        })
      }
      if (layerEnabled('signal')) for (const signal of chan.signals ?? []) {
        if (!dateIndex.has(signal.date) || !Number.isFinite(signal.price)) continue
        if (
          signal.type.startsWith('demark_')
          || signal.type.startsWith('segment_')
          || signal.type.startsWith('rsi_')
          || signal.type.startsWith('kdj_')
        ) continue
        const isBuy = signal.side === 'buy'
        const isMacd = signal.type === 'golden_cross' || signal.type === 'dead_cross'
        chanMarkPoints.push({
          coord: [signal.date, signal.price],
          symbol: isMacd ? 'circle' : 'diamond',
          symbolSize: isMacd ? 10 : 13,
          itemStyle: { color: isBuy ? '#34D399' : '#FB7185', borderColor: '#18181B', borderWidth: 1 },
          label: {
            show: true,
            formatter: signal.label,
            color: isBuy ? '#6EE7B7' : '#FDA4AF',
            fontSize: 8,
            position: isBuy ? 'bottom' : 'top',
          },
        })
      }
      if (layerEnabled('segmentSignal')) for (const signal of chan.segment_signals ?? []) {
        if (!dateIndex.has(signal.date) || !Number.isFinite(signal.price)) continue
        const isBuy = signal.side === 'buy'
        chanMarkPoints.push({
          coord: [signal.date, signal.price],
          symbol: 'diamond',
          symbolSize: 15,
          itemStyle: { color: isBuy ? '#F97316' : '#EA580C', borderColor: '#18181B', borderWidth: 1 },
          label: {
            show: true,
            formatter: signal.label,
            color: isBuy ? '#FDBA74' : '#FB923C',
            fontSize: 8,
            position: isBuy ? 'bottom' : 'top',
          },
        })
      }
      if (layerEnabled('wyckoff')) for (const event of wyckoffEvents) {
        if (!dateIndex.has(event.date)) continue
        const color = event.side === 'buy' ? '#34D399' : event.side === 'sell' ? '#FB7185' : '#FBBF24'
        chanMarkPoints.push({
          coord: [event.date, event.price],
          symbol: event.side === 'buy' ? 'diamond' : event.side === 'sell' ? 'triangle' : 'circle',
          symbolRotate: event.side === 'sell' ? 180 : 0,
          symbolSize: event.type === 'SOS' || event.type === 'SOW' ? 15 : 12,
          itemStyle: { color, borderColor: '#111827', borderWidth: 1 },
          label: {
            show: true,
            formatter: event.type,
            color,
            fontSize: 8,
            fontWeight: 'bold',
            position: event.side === 'sell' ? 'top' : 'bottom',
          },
        })
      }
      if (layerEnabled('demark')) for (const signal of chan.demark?.signals ?? []) {
        if (!dateIndex.has(signal.date) || !Number.isFinite(signal.price)) continue
        const isBuy = signal.side === 'buy'
        chanMarkPoints.push({
          coord: [signal.date, signal.price],
          symbol: 'pin',
          symbolSize: 22,
          itemStyle: { color: isBuy ? '#E11D48' : '#BE123C', borderColor: '#18181B', borderWidth: 1 },
          label: {
            show: true,
            formatter: signal.label,
            color: '#FDA4AF',
            fontSize: 8,
            fontWeight: 'bold',
            position: isBuy ? 'bottom' : 'top',
          },
        })
      }
      if (layerEnabled('demark')) {
        for (const [index, count] of (chan.demark?.setup ?? []).entries()) {
          if (!count || Math.abs(count) >= 9 || !dateIndex.has(dates[index])) continue
          const isSellSetup = count > 0
          chanMarkPoints.push({
            coord: [dates[index], isSellSetup ? rows[index].high : rows[index].low],
            symbol: 'none',
            label: {
              show: true,
              formatter: `${isSellSetup ? 'S' : 'B'}${Math.abs(count)}`,
              color: isSellSetup ? '#FDA4AF' : '#FCA5A5',
              fontSize: 7,
              position: isSellSetup ? 'top' : 'bottom',
            },
          })
        }
      }
      if (layerEnabled('rsi')) for (const signal of chan.rsi?.signals ?? []) {
        if (!dateIndex.has(signal.date) || !Number.isFinite(signal.price)) continue
        const isBuy = signal.side === 'buy'
        chanMarkPoints.push({
          coord: [signal.date, signal.price],
          symbol: 'circle',
          symbolSize: 9,
          itemStyle: { color: isBuy ? '#F59E0B' : '#D97706' },
          label: { show: true, formatter: signal.label, color: '#FCD34D', fontSize: 7, position: isBuy ? 'bottom' : 'top' },
        })
      }
      if (layerEnabled('kdj')) for (const signal of chan.kdj?.signals ?? []) {
        if (!dateIndex.has(signal.date) || !Number.isFinite(signal.price)) continue
        const isBuy = signal.side === 'buy'
        chanMarkPoints.push({
          coord: [signal.date, signal.price],
          symbol: 'circle',
          symbolSize: 8,
          itemStyle: { color: isBuy ? '#A78BFA' : '#7C3AED' },
          label: { show: true, formatter: signal.label, color: '#C4B5FD', fontSize: 7, position: isBuy ? 'bottom' : 'top' },
        })
      }
      if (layerEnabled('zone')) for (const zone of chan.zones ?? []) {
        if (!dateIndex.has(zone.start_date) || !dateIndex.has(zone.end_date)) continue
        chanMarkAreas.push([
          {
            name: '中枢',
            xAxis: zone.start_date,
            yAxis: zone.lower,
            itemStyle: { color: 'rgba(14, 165, 233, 0.10)' },
            label: { show: true, color: '#38BDF8', fontSize: 9, position: 'insideTop' },
          },
          { xAxis: zone.end_date, yAxis: zone.upper },
        ])
      }
      if (layerEnabled('eigen')) for (const eigen of chan.eigen ?? []) {
        if (!dateIndex.has(eigen.start_date) || !dateIndex.has(eigen.end_date)) continue
        chanMarkAreas.push([
          {
            name: eigen.gap ? '特征缺口' : '特征序列',
            xAxis: eigen.start_date,
            yAxis: eigen.low,
            itemStyle: { color: eigen.gap ? 'rgba(249, 115, 22, 0.10)' : 'rgba(249, 115, 22, 0.045)' },
            label: { show: false },
          },
          { xAxis: eigen.end_date, yAxis: eigen.high },
        ])
      }
      if (layerEnabled('segzs')) for (const zone of chan.segment_zones ?? []) {
        if (!dateIndex.has(zone.start_date) || !dateIndex.has(zone.end_date)) continue
        chanMarkAreas.push([
          {
            name: '线段中枢',
            xAxis: zone.start_date,
            yAxis: zone.lower,
            itemStyle: { color: 'rgba(20, 184, 166, 0.10)' },
            label: { show: true, color: '#5EEAD4', fontSize: 8, position: 'insideBottom' },
          },
          { xAxis: zone.end_date, yAxis: zone.upper },
        ])
      }
      if (layerEnabled('multilevel')) {
        const timeframeMeta: Record<string, { label: string; color: string }> = {
          '1w': { label: '周线中枢', color: '#C084FC' },
          '1M': { label: '月线中枢', color: '#E879F9' },
        }
        for (const [timeframe, higher] of Object.entries(chan.multi_level ?? {})) {
          const meta = timeframeMeta[timeframe]
          if (!meta) continue
          for (const zone of higher.zones ?? []) {
            if (!dateIndex.has(zone.start_date) || !dateIndex.has(zone.end_date)) continue
            chanMarkAreas.push([
              {
                name: meta.label,
                xAxis: zone.start_date,
                yAxis: zone.lower,
                itemStyle: { color: meta.color + '16', borderColor: meta.color + '88', borderWidth: 1 },
                label: { show: true, color: meta.color, fontSize: 8, position: 'insideTop' },
              },
              { xAxis: zone.end_date, yAxis: zone.upper },
            ])
          }
        }
      }
      if (layerEnabled('nesting')) for (const point of chan.interval_nesting ?? []) {
        if (!dateIndex.has(point.date) || !Number.isFinite(point.price)) continue
        chanMarkPoints.push({
          coord: [point.date, point.price],
          symbol: point.direction_alignment ? 'diamond' : 'circle',
          symbolSize: point.direction_alignment ? 16 : 11,
          itemStyle: {
            color: point.direction_alignment ? '#FDE047' : '#A16207',
            borderColor: '#422006',
            borderWidth: 1,
          },
          label: {
            show: true,
            formatter: () => `${point.parent_timeframe === '1w' ? '周' : '月'}套`,
            color: '#FEF9C3',
            fontSize: 7,
            position: point.side === 'buy' ? 'bottom' : 'top',
          },
        })
      }
    }

    // 动态布局:主图 / 成交量 / MACD、RSI、KDJ副图 / 缩放条,各段之间留间距
    const SLIDER_H = 22
    const PAD_TOP = 16
    const GAP_MAIN_VOL = 8
    const PANE_H = 92
    const PANE_GAP = 8
    const paneCount = Number(showMacd) + Number(showRsi) + Number(showKdj)
    const indicatorHeight = paneCount > 0 ? paneCount * PANE_H + (paneCount - 1) * PANE_GAP : 0
    const GAP_INDICATOR_SLIDER = paneCount > 0 ? 12 : 0
    const GAP_VOL_SLIDER = paneCount > 0 ? 0 : 12
    const PAD_BOTTOM = 8
    const volH = VOL_PANE_H
    const mainH = height - PAD_TOP - GAP_MAIN_VOL - volH - (paneCount > 0 ? PANE_GAP + indicatorHeight : 0) - GAP_INDICATOR_SLIDER - GAP_VOL_SLIDER - SLIDER_H - PAD_BOTTOM
    const volTop = PAD_TOP + mainH + GAP_MAIN_VOL
    const paneTop = volTop + volH + (paneCount > 0 ? PANE_GAP : 0)
    let nextPaneIndex = 2
    const macdPaneIndex = showMacd ? nextPaneIndex++ : null
    const rsiPaneIndex = showRsi ? nextPaneIndex++ : null
    const kdjPaneIndex = showKdj ? nextPaneIndex++ : null
    const sliderBottom = PAD_BOTTOM

    // 预留:markPoint(新闻标记)
    const markPointData: any[] = (markers ?? [])
      .filter(m => dateIndex.has(m.date))
      .map(m => ({
        coord: [m.date, rows[dateIndex.get(m.date)!].high],
        symbol: 'pin', symbolSize: 32,
        itemStyle: { color: m.color ?? '#EAB308' },
        label: { show: !!m.label, formatter: m.label ?? '', fontSize: 9, color: '#fff' },
      }))

    // 预留:markArea(事件区间)
    const markAreaData: any[] = (ranges ?? [])
      .filter(r => dateIndex.has(r.start) && dateIndex.has(r.end))
      .map(r => [{
        xAxis: r.start, name: r.label ?? '',
        itemStyle: { color: r.color ?? 'rgba(234,179,8,0.08)' },
        label: r.label ? { show: true, position: 'insideTop', distance: 6, color: '#EAB308', fontSize: 10 } : undefined,
      }, { xAxis: r.end }])

    const series: any[] = [
      {
        name: 'K', type: 'candlestick', data: candle, animation: false,
        // z=2 让蜡烛始终在价位线(z=1)之上, hover 高亮价位线时不会被遮挡/变淡
        z: 2,
        itemStyle: {
          color: THEME.bull, color0: THEME.bear,
          borderColor: THEME.bull, borderColor0: THEME.bear,
        },
        markPoint: [...markPointData, ...chanMarkPoints].length
          ? { data: [...markPointData, ...chanMarkPoints], animation: false }
          : undefined,
        markArea: [...markAreaData, ...chanMarkAreas].length
          ? { silent: true, data: [...markAreaData, ...chanMarkAreas] }
          : undefined,
      },
      {
        name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
        data: vols, animation: false,
      },
    ]

    // 价位水平线 —— 用 line series(恒定值)画水平线,endLabel 显示标签文字;
    // 与通道曲线一致,标签落在右侧 grid.right 预留带(外侧),不压蜡烛。
    // hoveredKey 非空时:命中线加粗高亮,其它线淡化(opacity 0.15),形成聚焦效果。
    const dimming = hoveredKey != null
    for (const p of priceLines) {
      const k = levelKey(p.type, p.value)
      const hit = hoveredKey === k
      const opacity = dimming ? (hit ? 1 : 0.12) : 0.7
      const width = hit ? 2 : 1
      series.push({
        name: p.label, type: 'line', silent: false, animation: false,
        symbol: 'none',
        data: dates.map(() => p.value),
        // 默认 z=1 在蜡烛(z=2)之下; 命中时 zlevel=10 提到独立顶层, 标签不再被遮挡
        z: 1,
        zlevel: hit ? 10 : 0,
        lineStyle: { width, color: p.color, type: 'dashed', opacity },
        itemStyle: { color: p.color },
        endLabel: {
          show: true,
          formatter: () => `${p.label} ${p.value.toFixed(2)}`,
          color: p.color, fontSize: hit ? 10 : 9, fontFamily: 'JetBrains Mono, monospace',
          fontWeight: hit ? 'bold' : 'normal',
          backgroundColor: hit ? CT().tooltipBg : CT().infoBarBg,
          borderColor: hit ? p.color : 'transparent',
          borderWidth: hit ? 1 : 0,
          padding: [2, 5], borderRadius: 2,
          distance: 6,
        },
      })
    }

    // 带状曲线指标(布林带 / Keltner通道 / ATR波动通道) —— 跟随行情漂移的曲线
    // 单一数据源 CURVE_DEFS 驱动:每条曲线带 endLabel(右侧端点标签),显示最新数值
    for (const def of CURVE_DEFS) {
      if (!activeTypes.has(def.group)) continue
      const data = alignedSeries[def.alignedKey]
      if (!data || !data.some(v => v != null)) continue
      // 取最后一个有效值作为右侧端点显示文字
      let lastVal: number | null = null
      for (let i = data.length - 1; i >= 0; i--) {
        if (data[i] != null) { lastVal = data[i]; break }
      }
      // 曲线 key 用 group(同组上下轨联动),hover 命中时高亮
      const hit = hoveredKey === def.group
      const opacity = dimming ? (hit ? 1 : 0.12) : 0.8
      const width = hit ? 1.8 : 1
      series.push({
        name: def.endLabel, type: 'line', data: data.map(v => v ?? '-'),
        smooth: true, symbol: 'none', silent: false, animation: false,
        z: 1,
        zlevel: hit ? 10 : 0,
        lineStyle: { width, color: def.color, type: def.dashed === false ? 'solid' : 'dashed', opacity },
        itemStyle: { color: def.color },
        // 右侧端点标签:显示该通道的最新数值,距绘图区右缘留 6px 间距
        endLabel: lastVal != null ? {
          show: true,
          formatter: () => `${lastVal!.toFixed(2)}`,
          color: def.color, fontSize: hit ? 10 : 9, fontFamily: 'JetBrains Mono, monospace',
          fontWeight: hit ? 'bold' : 'normal',
          backgroundColor: hit ? CT().tooltipBg : CT().infoBarBg,
          borderColor: hit ? def.color : 'transparent',
          borderWidth: hit ? 1 : 0,
          padding: [2, 5], borderRadius: 2,
          distance: 6,
        } : undefined,
      })
    }

    // 填充 seriesIndex → levelKey 映射(K/成交量索引 0/1 不参与联动)
    const keyMap = new Map<number, string>()
    // series[0]=K线, series[1]=成交量, 之后是按 priceLines + CURVE_DEFS 顺序 push 的
    let si = 2
    for (const p of priceLines) {
      keyMap.set(si++, levelKey(p.type, p.value))
    }
    for (const def of CURVE_DEFS) {
      if (!activeTypes.has(def.group)) continue
      const data = alignedSeries[def.alignedKey]
      if (!data || !data.some(v => v != null)) continue
      keyMap.set(si++, def.group)
    }

    // 缠论指标线放在价位曲线之后, 不参与价位 hover 索引。
    if (chan && showChan) {
      if (layerEnabled('ma')) {
        const maDefs = [
          { key: 'ma5', label: 'MA5', color: '#FACC15' },
          { key: 'ma10', label: 'MA10', color: '#FB923C' },
          { key: 'ma20', label: 'MA20', color: '#F472B6' },
          { key: 'ma30', label: 'MA30', color: '#A78BFA' },
          { key: 'ma60', label: 'MA60', color: '#38BDF8' },
          { key: 'ma120', label: 'MA120', color: '#34D399' },
        ]
        for (const def of maDefs) {
          const data = chan.moving_averages?.[def.key]
          if (!data?.some(value => value != null)) continue
          series.push({
            name: def.label,
            type: 'line',
            data: data.map(value => value ?? '-'),
            symbol: 'none',
            smooth: true,
            silent: true,
            animation: false,
            z: 2,
            lineStyle: { width: def.key === 'ma20' ? 1.8 : 1, color: def.color, opacity: 0.8 },
          })
        }
      }

      if (layerEnabled('channel')) {
        const channel = chan.channel
        for (const def of [
          { key: 'upper', label: `通道上轨(${channel?.period ?? 20})`, color: '#06B6D4' },
          { key: 'lower', label: `通道下轨(${channel?.period ?? 20})`, color: '#06B6D4' },
        ] as const) {
          const data = channel?.[def.key]
          if (!data?.some(value => value != null)) continue
          series.push({
            name: def.label,
            type: 'line',
            data: data.map(value => value ?? '-'),
            symbol: 'none',
            smooth: false,
            silent: true,
            animation: false,
            z: 1,
            lineStyle: { width: 1.2, color: def.color, type: 'dashed', opacity: 0.75 },
          })
        }
      }

      if (layerEnabled('trendline')) for (const trendline of chan.trendlines ?? []) {
        if (!dateIndex.has(trendline.start_date) || !dateIndex.has(trendline.end_date)) continue
        series.push({
          name: trendline.label,
          type: 'line',
          data: [[trendline.start_date, trendline.start_price], [trendline.end_date, trendline.end_price]],
          symbol: 'none',
          silent: true,
          animation: false,
          z: 4,
          lineStyle: {
            width: 2,
            color: trendline.type === 'resistance' ? '#E879F9' : '#34D399',
            type: 'dashed',
            opacity: 0.9,
          },
        })
      }

      if (layerEnabled('bi')) for (const bi of chan.bis ?? []) {
        if (!dateIndex.has(bi.start_date) || !dateIndex.has(bi.end_date)) continue
        series.push({
          name: `${bi.direction === 'up' ? '向上' : '向下'}笔 ${bi.index + 1}`,
          type: 'line',
          data: [[bi.start_date, bi.start_price], [bi.end_date, bi.end_price]],
          symbol: 'none',
          silent: true,
          animation: false,
          z: 3,
          lineStyle: {
            width: 1.4,
            color: bi.direction === 'up' ? '#38BDF8' : '#A78BFA',
            opacity: 0.85,
          },
          endLabel: {
            show: true,
            formatter: () => `笔${bi.index + 1} ${bi.end_price.toFixed(2)}`,
            color: bi.direction === 'up' ? '#7DD3FC' : '#C4B5FD',
            fontSize: 8,
            distance: 3,
          },
        })
      }
      if (layerEnabled('segment')) for (const segment of chan.segments ?? []) {
        if (!dateIndex.has(segment.start_date) || !dateIndex.has(segment.end_date)) continue
        const startPrice = segment.start_price ?? (segment.direction === 'up' ? segment.low : segment.high)
        const endPrice = segment.end_price ?? (segment.direction === 'up' ? segment.high : segment.low)
        series.push({
          name: `${segment.direction === 'up' ? '向上线段' : '向下线段'} ${segment.index + 1}`,
          type: 'line',
          data: [[segment.start_date, startPrice], [segment.end_date, endPrice]],
          symbol: 'none',
          silent: true,
          animation: false,
          z: 4,
          lineStyle: {
            width: 2.4,
            color: segment.direction === 'up' ? '#0EA5E9' : '#8B5CF6',
            opacity: 0.8,
          },
        })
      }

      if (layerEnabled('demark')) {
        const demark = chan.demark
        for (const def of [
          { key: 'tdst_resistance', label: 'TDST压力', color: '#F43F5E' },
          { key: 'tdst_support', label: 'TDST支撑', color: '#FB7185' },
        ] as const) {
          const data = demark?.[def.key]
          if (!data?.some(value => value != null)) continue
          series.push({
            name: def.label,
            type: 'line',
            data: data.map(value => value ?? '-'),
            symbol: 'none',
            silent: true,
            animation: false,
            z: 1,
            lineStyle: { width: 1.2, color: def.color, type: 'dotted', opacity: 0.7 },
          })
        }
      }

      if (showMacd && macdPaneIndex != null) {
        const macd = chan.macd
        const hist = macd?.hist ?? []
        const dif = macd?.dif ?? []
        const dea = macd?.dea ?? []
        series.push({
          name: 'MACD柱',
          type: 'bar',
          xAxisIndex: macdPaneIndex,
          yAxisIndex: macdPaneIndex,
          data: hist.map(value => value ?? '-'),
          animation: false,
          barMaxWidth: 5,
          itemStyle: {
            color: (params: any) => (Number(params.value) >= 0 ? 'rgba(240,68,56,0.65)' : 'rgba(45,155,101,0.65)'),
          },
        })
        series.push({
          name: 'DIF',
          type: 'line',
          xAxisIndex: macdPaneIndex,
          yAxisIndex: macdPaneIndex,
          data: dif.map(value => value ?? '-'),
          symbol: 'none',
          animation: false,
          lineStyle: { width: 1.2, color: '#F59E0B' },
        })
        series.push({
          name: 'DEA',
          type: 'line',
          xAxisIndex: macdPaneIndex,
          yAxisIndex: macdPaneIndex,
          data: dea.map(value => value ?? '-'),
          symbol: 'none',
          animation: false,
          lineStyle: { width: 1.2, color: '#60A5FA' },
        })
      }

      if (showRsi && rsiPaneIndex != null) {
        const rsi = chan.rsi
        const values = rsi?.values ?? []
        series.push({
          name: 'RSI14',
          type: 'line',
          xAxisIndex: rsiPaneIndex,
          yAxisIndex: rsiPaneIndex,
          data: values.map(value => value ?? '-'),
          symbol: 'none',
          animation: false,
          lineStyle: { width: 1.6, color: '#F59E0B' },
          markLine: {
            silent: true,
            symbol: 'none',
            label: { show: true, color: '#A1A1AA', fontSize: 8 },
            lineStyle: { type: 'dashed', width: 1, color: '#71717A', opacity: 0.55 },
            data: [
              { yAxis: rsi?.overbought ?? 70, name: '70' },
              { yAxis: rsi?.midline ?? 50, name: '50' },
              { yAxis: rsi?.oversold ?? 30, name: '30' },
            ],
          },
        })
      }

      if (showKdj && kdjPaneIndex != null) {
        const kdj = chan.kdj
        const paneSeries = [
          { key: 'k', label: 'K', color: '#A78BFA' },
          { key: 'd', label: 'D', color: '#60A5FA' },
          { key: 'j', label: 'J', color: '#F472B6' },
        ] as const
        for (const def of paneSeries) {
          const data = kdj?.[def.key] ?? []
          series.push({
            name: `KDJ-${def.label}`,
            type: 'line',
            xAxisIndex: kdjPaneIndex,
            yAxisIndex: kdjPaneIndex,
            data: data.map(value => value ?? '-'),
            symbol: 'none',
            animation: false,
            lineStyle: { width: def.key === 'j' ? 1 : 1.5, color: def.color },
            markLine: def.key === 'k' ? {
              silent: true,
              symbol: 'none',
              label: { show: true, color: '#A1A1AA', fontSize: 8 },
              lineStyle: { type: 'dashed', width: 1, color: '#71717A', opacity: 0.5 },
              data: [{ yAxis: 80, name: '80' }, { yAxis: 20, name: '20' }],
            } : undefined,
          })
        }
      }
    }
    seriesKeyMapRef.current = keyMap

    return {
      animation: false,
      backgroundColor: 'transparent',
      // grid.right 留出足够宽度给价位标签文字区:蜡烛只占左侧主区域,
      // 价位线右端的标签文字显示在这条预留带里,不压在蜡烛上。
      // 预留 ~144px:最长标签(如「成交密集区(POC) 12.34」)约 13 字符,fontSize 9 等宽。
      grid: [
        { left: 56, right: 144, top: 16, height: mainH },
        { left: 56, right: 144, top: volTop, height: volH },
        ...(paneCount > 0
          ? [showMacd, showRsi, showKdj]
            .filter(Boolean)
            .map((_, index) => ({
              left: 56,
              right: 144,
              top: paneTop + index * (PANE_H + PANE_GAP),
              height: PANE_H,
            }))
          : []),
      ],
      xAxis: [
        {
          type: 'category', data: dates, boundaryGap: true,
          axisLine: { lineStyle: { color: CT().grid } },
          axisLabel: { color: CT().text, fontSize: 10 },
          splitLine: { show: false },
          axisPointer: { show: true, label: { show: false } },
        },
        {
          type: 'category', gridIndex: 1, data: dates, boundaryGap: true,
          axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false },
        },
        ...(paneCount > 0
          ? [showMacd, showRsi, showKdj]
            .filter(Boolean)
            .map((_, index) => ({
              type: 'category' as const,
              gridIndex: index + 2,
              data: dates,
              boundaryGap: true,
              axisLabel: { color: CT().text, fontSize: 9 },
              axisLine: { show: false },
              axisTick: { show: false },
            }))
          : []),
      ],
      yAxis: [
        { scale: true, splitLine: { lineStyle: { color: CT().grid } },
          axisLabel: { color: CT().text, fontSize: 10, fontFamily: 'JetBrains Mono, monospace' } },
        { scale: true, gridIndex: 1, splitNumber: 2,
          // 成交量区不画背景横线
          splitLine: { show: false },
          axisLabel: { color: CT().text, fontSize: 9, fontFamily: 'JetBrains Mono, monospace',
                       formatter: (v: number) => fmtVol(v) } },
        ...(paneCount > 0
          ? [showMacd, showRsi, showKdj]
            .filter(Boolean)
            .map((_, index) => ({
              scale: true,
              gridIndex: index + 2,
              splitNumber: 3,
              min: index === (rsiPaneIndex ?? -1) - 2 ? 0 : undefined,
              max: index === (rsiPaneIndex ?? -1) - 2 ? 100 : undefined,
              splitLine: { lineStyle: { color: CT().grid } },
              axisLabel: { color: CT().text, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' },
            }))
          : []),
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, ...Array.from({ length: paneCount }, (_, index) => index + 2)], start: zoomStart, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, ...Array.from({ length: paneCount }, (_, index) => index + 2)], bottom: sliderBottom, height: SLIDER_H, start: zoomStart, end: 100,
          borderColor: 'transparent', fillerColor: CT().zoomFill,
          handleStyle: { color: '#52525B' }, textStyle: { color: CT().text, fontSize: 10 } },
      ],
      // 不弹 hover tooltip(用户要求);但保留十字线 axisPointer 作为缩放/定位参照
      tooltip: { show: false },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      series,
    }
  }

  // 初始化 + 数据更新
  useEffect(() => {
    if (!chartRef.current) return
    if (!chartInstRef.current) {
      chartInstRef.current = echarts.init(chartRef.current, undefined, { renderer: 'canvas' })
      chartInstRef.current.on('click', (params: any) => {
        // 预留:点击 K 线(非 markPoint/markLine)回调
        if (params.componentType === 'series' && params.seriesType === 'candlestick' && onDateClick) {
          onDateClick(dates[params.dataIndex])
        }
      })
      // hover 价位线/曲线 endLabel → 联动高亮(与下方文字行双向联动)
      chartInstRef.current.on('mouseover', (params: any) => {
        if (params.componentType === 'series') {
          const k = seriesKeyMapRef.current.get(params.seriesIndex as number)
          if (k) setHoveredKey(k)
        }
      })
      chartInstRef.current.on('globalout', () => setHoveredKey(null))
    }
    chartInstRef.current.setOption(buildOption(), true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, levels, series, seriesDates, chan, showChan, activeChanLayers, activeTypes, pivotRank, markers, ranges, height, theme, hoveredKey])

  // resize
  useEffect(() => {
    const inst = chartInstRef.current
    if (!inst) return
    const onResize = () => inst.resize()
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); inst.dispose(); chartInstRef.current = null }
  }, [])

  const toggleType = (t: LevelType) => {
    setActiveTypes(prev => {
      const next = new Set(prev)
      if (next.has(t)) next.delete(t)
      else next.add(t)
      return next
    })
  }

  const toggleChanLayer = (layer: ChanLayer) => {
    setActiveChanLayers(prev => {
      const next = new Set(prev)
      if (next.has(layer)) next.delete(layer)
      else next.add(layer)
      return next
    })
  }

  return (
    <div className={className}>
      {/* 价位开关按钮组 */}
      {levels && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-[10px] text-muted mr-1">关键价位</span>
          {LEVEL_GROUPS.map(g => {
            const active = activeTypes.has(g.key)
            // 枢轴点数量按当前档位过滤显示;其他组显示原始数量
            const raw = levels[g.key] ?? []
            const count = g.key === 'pivot'
              ? raw.filter(p => p.rank === undefined || p.rank <= pivotRank).length
              : raw.length
            return (
              <button
                key={g.key}
                onClick={() => {
                  toggleType(g.key)
                  setExplanationSelection({ kind: 'level', key: g.key })
                }}
                disabled={raw.length === 0}
                title={`${g.label} (${count} 个)`}
                className={`inline-flex items-center gap-1 h-6 px-2 rounded-md text-[10px] font-medium border transition-all disabled:opacity-30 disabled:cursor-not-allowed ${
                  active
                    ? 'text-foreground'
                    : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
                }`}
                style={active ? { borderColor: g.color + '66', backgroundColor: g.color + '1a' } : undefined}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: active ? g.color : '#52525B' }} />
                {g.label}
                <span className="opacity-50">{count}</span>
              </button>
            )
          })}

          {/* 枢轴点档位选择器 —— 仅当枢轴点开启时显示 */}
          {activeTypes.has('pivot') && (levels.pivot?.length ?? 0) > 0 && (
            <div className="inline-flex items-center gap-0.5 ml-1 pl-2 border-l border-border/40">
              <span className="text-[10px] text-muted mr-1">档位</span>
              {([1, 2, 3] as const).map(r => (
                <button
                  key={r}
                  onClick={() => setPivotRank(r)}
                  title={r === 1 ? 'P + R1/S1(3 个)' : r === 2 ? '到 R2/S2(5 个)' : '全档 R3/S3(7 个)'}
                  className={`h-6 px-2 rounded-md text-[10px] font-mono border transition-all ${
                    pivotRank === r
                      ? 'bg-[#8B5CF6]/15 border-[#8B5CF6]/40 text-[#c4b5fd]'
                      : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {chan && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-muted mr-1">缠论图层</span>
          <span className="mr-1 rounded border border-border/40 bg-base/30 px-1.5 py-1 text-[9px] text-muted">
            已计算级别: {(chan.timeframes ?? ['1d']).map(timeframeLabel).join(' / ')}
          </span>
          <button
            type="button"
            onClick={() => {
              setShowChan(value => !value)
              setExplanationSelection({ kind: 'chan', key: 'all' })
            }}
            className={`inline-flex items-center gap-1 h-6 px-2 rounded-md text-[10px] font-medium border transition-all ${
              showChan
                ? 'text-sky-300 border-sky-400/40 bg-sky-400/10'
                : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
            }`}
            title="显示或隐藏全部缠论图层"
          >
            <span className={`h-1.5 w-1.5 rounded-full ${showChan ? 'bg-sky-400' : 'bg-zinc-600'}`} />
            缠论
            <span className="opacity-60">
              {chan.bis?.length ?? 0}笔 · {chan.zones?.length ?? 0}中枢
            </span>
          </button>
          {CHAN_LAYER_GROUPS.map(layer => {
            const active = showChan && activeChanLayers.has(layer.key)
            const count = layer.key === 'point'
              ? (chan.points?.length ?? 0)
              : layer.key === 'signal'
                ? (chan.signals ?? []).filter(signal => (
                  !signal.type.startsWith('demark_')
                  && !signal.type.startsWith('segment_')
                  && !signal.type.startsWith('rsi_')
                  && !signal.type.startsWith('kdj_')
                )).length
                : layer.key === 'eigen'
                    ? (chan.eigen?.length ?? 0)
                    : layer.key === 'cbsp'
                      ? (chan.cbsp_points?.length ?? 0)
                    : layer.key === 'segmentSignal'
                      ? (chan.segment_signals?.length ?? 0)
                    : layer.key === 'segzs'
                      ? (chan.segment_zones?.length ?? 0)
                      : layer.key === 'multilevel'
                        ? Object.values(chan.multi_level ?? {}).reduce((sum, item) => sum + item.zones.length, 0)
                        : layer.key === 'nesting'
                          ? (chan.interval_nesting?.length ?? 0)
                          : layer.key === 'wyckoff'
                            ? wyckoffEvents.length
                      : layer.key === 'demark'
                        ? (chan.demark?.signals?.length ?? 0)
                        : layer.key === 'rsi'
                          ? (chan.rsi?.signals?.length ?? 0)
                          : layer.key === 'kdj'
                            ? (chan.kdj?.signals?.length ?? 0)
                  : null
            return (
              <button
                key={layer.key}
                type="button"
                onClick={() => {
                  toggleChanLayer(layer.key)
                  setExplanationSelection({ kind: 'chan', key: layer.key })
                }}
                className={`inline-flex items-center gap-1 h-6 px-2 rounded-md text-[10px] font-medium border transition-all ${
                  active
                    ? 'text-foreground'
                    : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
                }`}
                style={active ? { borderColor: layer.color + '66', backgroundColor: layer.color + '1a' } : undefined}
                title={`显示或隐藏${layer.label}`}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: active ? layer.color : '#52525B' }} />
                {layer.label}
                {count != null && <span className="opacity-50">{count}</span>}
              </button>
            )
          })}
        </div>
      )}
      {chan && (
        <SignalExplanation
          selection={explanationSelection}
          levels={levels}
          chan={chan}
          wyckoffEvents={wyckoffEvents}
          showChan={showChan}
          activeTypes={activeTypes}
          activeChanLayers={activeChanLayers}
          onSelect={setExplanationSelection}
        />
      )}
      {/* 图表:右侧预留带(grid.right 预留)显示价位标签文字,不压蜡烛 */}
      <div ref={chartRef} style={{ width: '100%', height }} />

      {/* 价位统计面板:把当前开启的点位按"压力 / 支撑"结构化列出 */}
      {levels && (
        <LevelOverview
          levels={levels}
          activeTypes={activeTypes}
          pivotRank={pivotRank}
          close={rows.length ? rows[rows.length - 1].close : undefined}
          rows={rows}
          chan={chan}
          hoveredKey={hoveredKey}
          onHover={setHoveredKey}
        />
      )}
    </div>
  )
}

function SignalExplanation({
  selection,
  levels,
  chan,
  wyckoffEvents,
  showChan,
  activeTypes,
  activeChanLayers,
  onSelect,
}: {
  selection: ExplanationSelection | null
  levels?: Record<LevelType, PriceLevel[]>
  chan: StockChanAnalysis
  wyckoffEvents: WyckoffEvent[]
  showChan: boolean
  activeTypes: Set<LevelType>
  activeChanLayers: Set<ChanLayer>
  onSelect: (selection: ExplanationSelection) => void
}) {
  const fallback: ExplanationSelection = chan
    ? { kind: 'chan', key: 'all' }
    : { kind: 'level', key: 'sr' }
  const current = selection ?? fallback
  const isLevel = current.kind === 'level'
  const levelDefinition = isLevel ? LEVEL_EXPLANATIONS[current.key] : undefined
  const chanDefinition = !isLevel && current.key !== 'all'
    ? CHAN_LAYER_EXPLANATIONS[current.key]
    : undefined
  const group = isLevel
    ? LEVEL_GROUPS.find(item => item.key === current.key)
    : current.key === 'all'
      ? { label: '全部缠论', color: '#38BDF8' }
      : CHAN_LAYER_GROUPS.find(item => item.key === current.key)
  const count = isLevel
    ? (levels?.[current.key] ?? []).length
    : current.key === 'all'
      ? chan.bis.length + chan.segments.length + chan.zones.length
      : chanLayerCount(chan, current.key, wyckoffEvents)
  const enabled = isLevel
    ? activeTypes.has(current.key)
    : current.key === 'all'
      ? showChan
      : showChan && activeChanLayers.has(current.key)
  const latestSignal = !isLevel && current.key !== 'all'
    ? chanLayerLatestSignal(chan, current.key, wyckoffEvents)
    : current.key === 'all'
      ? chan.signals.at(-1) ?? null
      : null

  return (
    <div className="mb-3 rounded-lg border border-border/50 bg-base/25 overflow-hidden">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-border/40 px-3 py-2">
        <span className="text-[10px] font-medium text-muted mr-1">信号解释</span>
        {LEVEL_GROUPS.map(item => (
          <button
            key={`explain-level-${item.key}`}
            type="button"
            onClick={() => onSelect({ kind: 'level', key: item.key })}
            className={`h-5 rounded px-1.5 text-[9px] border transition-colors ${
              isLevel && current.key === item.key
                ? 'text-foreground border-border/80 bg-elevated/70'
                : 'text-muted border-transparent hover:border-border/50'
            }`}
          >
            {item.label}
          </button>
        ))}
        <span className="mx-0.5 h-3 border-l border-border/40" />
        <button
          type="button"
          onClick={() => onSelect({ kind: 'chan', key: 'all' })}
          className={`h-5 rounded px-1.5 text-[9px] border transition-colors ${
            !isLevel && current.key === 'all'
              ? 'text-foreground border-border/80 bg-elevated/70'
              : 'text-muted border-transparent hover:border-border/50'
          }`}
        >
          全部缠论
        </button>
        {CHAN_LAYER_GROUPS.map(item => (
          <button
            key={`explain-chan-${item.key}`}
            type="button"
            onClick={() => onSelect({ kind: 'chan', key: item.key })}
            className={`h-5 rounded px-1.5 text-[9px] border transition-colors ${
              !isLevel && current.key === item.key
                ? 'text-foreground border-border/80 bg-elevated/70'
                : 'text-muted border-transparent hover:border-border/50'
            }`}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="grid gap-3 px-3 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: group?.color ?? '#71717A' }} />
            <span className="text-xs font-medium text-foreground">{group?.label ?? '缠论图层'}</span>
            <span className={`rounded px-1.5 py-0.5 text-[9px] ${
              enabled ? 'bg-emerald-400/10 text-emerald-300' : 'bg-zinc-500/10 text-muted'
            }`}>
              {enabled ? '已显示' : '未显示'}
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-secondary">
            {levelDefinition?.summary ?? chanDefinition?.summary ?? '汇总缠论结构线、区间和辅助信号。'}
          </p>
          <p className="mt-1 text-[10px] leading-relaxed text-muted">
            使用提示：{levelDefinition?.usage ?? chanDefinition?.usage ?? '点击上方具体图层查看对应定义和最近信号。'}
          </p>
        </div>
        <div className="grid min-w-[150px] grid-cols-2 gap-x-4 gap-y-1 self-start text-[10px]">
          <span className="text-muted">当前数量</span>
          <span className="text-right font-mono text-foreground">{count}</span>
          <span className="text-muted">最近信号</span>
          <span className="text-right font-mono text-foreground">
            {latestSignal ? `${latestSignal.label} ${latestSignal.date}` : '暂无'}
          </span>
        </div>
      </div>
    </div>
  )
}

function chanLayerCount(chan: StockChanAnalysis, key: ChanLayer, wyckoffEvents: WyckoffEvent[]): number {
  switch (key) {
    case 'fractal': return chan.fractals.length
    case 'bi': return chan.bis.length
    case 'segment': return chan.segments.length
    case 'zone': return chan.zones.length
    case 'point': return chan.points.length
    case 'cbsp': return chan.cbsp_points?.length ?? 0
    case 'eigen': return chan.eigen.length
    case 'trendline': return chan.trendlines.length
    case 'ma': return Object.values(chan.moving_averages).filter(values => values.some(value => value != null)).length
    case 'channel': return chan.channel.breakouts.length
    case 'signal': return chan.signals.length
    case 'segmentSignal': return chan.segment_signals.length
    case 'segzs': return chan.segment_zones.length
    case 'multilevel': return Object.values(chan.multi_level ?? {}).reduce((sum, item) => sum + item.zones.length, 0)
    case 'nesting': return chan.interval_nesting?.length ?? 0
    case 'demark': return chan.demark.signals.length
    case 'macd': return chan.macd.crosses.length
    case 'rsi': return chan.rsi.signals.length
    case 'kdj': return chan.kdj.signals.length
    case 'wyckoff': return wyckoffEvents.length
  }
}

function chanLayerLatestSignal(
  chan: StockChanAnalysis,
  key: ChanLayer,
  wyckoffEvents: WyckoffEvent[],
): { date: string; label: string } | null {
  const signals = key === 'signal'
    ? chan.signals
      : key === 'segmentSignal'
        ? chan.segment_signals
        : key === 'cbsp'
          ? chan.cbsp_points ?? []
          : key === 'nesting'
            ? chan.interval_nesting ?? []
      : key === 'demark'
        ? chan.demark.signals
        : key === 'macd'
          ? chan.macd.crosses
          : key === 'rsi'
            ? chan.rsi.signals
            : key === 'kdj'
              ? chan.kdj.signals
              : key === 'channel'
                ? chan.channel.breakouts
                : key === 'wyckoff'
                  ? wyckoffEvents
                : key === 'point'
                  ? chan.points
                  : key === 'segment'
                    ? chan.segment_signals
                    : []
  return signals.at(-1) ?? null
}

// ===== 价位统计面板(图表下方,结构化文本展示) =====
function LevelOverview({
  levels, activeTypes, pivotRank, close, rows, chan, hoveredKey, onHover,
}: {
  levels: Record<LevelType, PriceLevel[]>
  activeTypes: Set<LevelType>
  pivotRank: 1 | 2 | 3
  close?: number
  rows: KlineRow[]
  chan?: StockChanAnalysis
  hoveredKey: string | null
  onHover: (k: string | null) => void
}) {
  // 收集当前显示的点位(同 collectPriceLines 的过滤逻辑)
  const visible: PriceLevel[] = []
  for (const g of LEVEL_GROUPS) {
    if (!activeTypes.has(g.key)) continue
    for (const p of levels[g.key] ?? []) {
      if (p.type === 'pivot' && p.rank !== undefined && p.rank > pivotRank) continue
      visible.push(p)
    }
  }
  if (visible.length === 0) return null

  // 按方向分两组:压力位(在当前价之上) / 支撑位(之下),各自按距当前价远近排序
  const cur = close ?? visible[0].value
  const resistances = visible
    .filter(p => p.side === 'resistance')
    .sort((a, b) => a.value - b.value)        // 由近及远(低→高)
  const supports = visible
    .filter(p => p.side === 'support')
    .sort((a, b) => b.value - a.value)         // 由近及远(高→低)
  const neutrals = visible.filter(p => p.side === 'neutral')

  const fmtPct = (v: number) => {
    if (!cur) return ''
    const pct = ((v - cur) / cur) * 100
    const sign = pct >= 0 ? '+' : ''
    return `${sign}${pct.toFixed(1)}%`
  }

  const Row = ({ p }: { p: PriceLevel }) => {
    const color = LEVEL_GROUPS.find(g => g.key === p.type)?.color ?? CT().text
    const k = levelKey(p.type, p.value)
    const hit = hoveredKey === k
    const dim = hoveredKey != null && !hit
    return (
      <div
        onMouseEnter={() => onHover(k)}
        onMouseLeave={() => onHover(null)}
        className={`flex items-center gap-2 py-0.5 px-1.5 -mx-1.5 rounded transition-colors cursor-default ${
          hit ? 'bg-elevated/60' : ''
        }`}
        style={dim ? { opacity: 0.35 } : undefined}
      >
        <span className="h-1.5 w-1.5 rounded-full shrink-0 transition-transform" style={{ backgroundColor: color, transform: hit ? 'scale(1.5)' : 'scale(1)' }} />
        <span className={`text-[11px] w-24 shrink-0 truncate ${hit ? 'text-foreground font-medium' : 'text-secondary'}`}>{p.label}</span>
        <span className={`text-[11px] font-mono ${hit ? 'text-foreground font-bold' : 'text-foreground'}`}>{p.value.toFixed(2)}</span>
        <span className="text-[9px] font-mono text-muted">{fmtPct(p.value)}</span>
      </div>
    )
  }

  return (
    <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(260px,0.82fr)_minmax(380px,1.18fr)]">
      <div className="rounded-lg border border-border/40 bg-base/20 px-3 py-2">
        {/* 当前价 */}
        <div className="flex items-center gap-2 pb-1 border-b border-border/30 mb-1">
          <span className="text-[10px] text-muted">当前价</span>
          <span className="text-xs font-mono font-medium text-foreground">{cur.toFixed(2)}</span>
        </div>
        {/* 压力位(从近到远,即从低到高)倒序展示:最高的在最上 */}
        {resistances.length > 0 && (
          <div>
            <div className="text-[10px] font-medium text-bear mb-0.5">压力位 ↑</div>
            {[...resistances].reverse().map((p, i) => <Row key={`r-${i}`} p={p} />)}
          </div>
        )}
        {/* 支撑位 + 中性(枢轴位 P) */}
        <div className={resistances.length > 0 ? 'mt-2' : ''}>
          {supports.length > 0 && (
            <>
              <div className="text-[10px] font-medium text-bull mb-0.5">支撑位 ↓</div>
              {supports.map((p, i) => <Row key={`s-${i}`} p={p} />)}
            </>
          )}
          {neutrals.length > 0 && (
            <div className={supports.length > 0 ? 'mt-2' : ''}>
              {supports.length === 0 && <div className="text-[10px] font-medium text-muted mb-0.5">枢轴位</div>}
              {neutrals.map((p, i) => <Row key={`n-${i}`} p={p} />)}
            </div>
          )}
        </div>
      </div>
      <DecisionSummary rows={rows} levels={levels} chan={chan} close={cur} />
    </div>
  )
}

type SummaryTone = 'bull' | 'bear' | 'neutral'

interface SummaryLevel {
  level: PriceLevel
  direction: 'support' | 'resistance'
  distancePct: number
  advice: string
}

interface DecisionSummaryData {
  bias: string
  biasTone: SummaryTone
  newPosition: string
  holding: string
  trend: string
  trendTone: SummaryTone
  funds: string
  fundsTone: SummaryTone
  emotion: string
  emotionTone: SummaryTone
  levels: SummaryLevel[]
  reasons: string[]
  risks: string[]
}

function DecisionSummary({
  rows, levels, chan, close,
}: {
  rows: KlineRow[]
  levels: Record<LevelType, PriceLevel[]>
  chan?: StockChanAnalysis
  close: number
}) {
  const summary = buildDecisionSummary(rows, levels, chan, close)
  const toneClass = (tone: SummaryTone) => (
    tone === 'bull'
      ? 'text-bull'
      : tone === 'bear'
        ? 'text-bear'
        : 'text-warning'
  )
  const badgeClass = (tone: SummaryTone) => (
    tone === 'bull'
      ? 'border-bull/30 bg-bull/10 text-bull'
      : tone === 'bear'
        ? 'border-bear/30 bg-bear/10 text-bear'
        : 'border-warning/30 bg-warning/10 text-warning'
  )

  return (
    <section className="rounded-lg border border-border/40 bg-base/20 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/30 pb-2">
        <div>
          <div className="text-[10px] text-muted">综合研判 · 研究参考</div>
          <div className={`mt-0.5 text-sm font-semibold ${toneClass(summary.biasTone)}`}>{summary.bias}</div>
        </div>
        <span className={`rounded border px-2 py-1 text-[10px] ${badgeClass(summary.biasTone)}`}>
          不替代人工决策
        </span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-1.5 xl:grid-cols-4">
        <SummaryMetric label="趋势" value={summary.trend} tone={summary.trendTone} />
        <SummaryMetric label="资金强弱" value={summary.funds} tone={summary.fundsTone} />
        <SummaryMetric label="情绪状态" value={summary.emotion} tone={summary.emotionTone} />
        <SummaryMetric label="数据日期" value={rows.at(-1)?.date ?? '--'} />
      </div>

      <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
        <SummaryAction label="新仓计划" value={summary.newPosition} />
        <SummaryAction label="已有仓位" value={summary.holding} />
      </div>

      {summary.levels.length > 0 && (
        <div className="mt-2 rounded border border-border/40 bg-surface/30 px-2.5 py-2">
          <div className="mb-1 text-[10px] font-medium text-secondary">重点观察价位</div>
          <div className="space-y-1.5">
            {summary.levels.map(item => (
              <div key={`${item.direction}-${item.level.type}-${item.level.value}`} className="grid grid-cols-[auto_auto_1fr] items-start gap-2 text-[10px]">
                <span className={item.direction === 'support' ? 'text-bull' : 'text-bear'}>
                  {item.direction === 'support' ? '支撑' : '压力'}
                </span>
                <span className="font-mono text-foreground">
                  {item.level.label} {item.level.value.toFixed(2)} ({item.distancePct >= 0 ? '+' : ''}{item.distancePct.toFixed(1)}%)
                </span>
                <span className="leading-relaxed text-muted">{item.advice}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <SummaryList title="主要依据" items={summary.reasons} tone="text-secondary" />
        <SummaryList title="风险与失效条件" items={summary.risks} tone="text-warning" />
      </div>
    </section>
  )
}

function SummaryMetric({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: SummaryTone }) {
  const color = tone === 'bull' ? 'text-bull' : tone === 'bear' ? 'text-bear' : 'text-foreground'
  return (
    <div className="rounded border border-border/40 bg-surface/30 px-2 py-1.5">
      <div className="text-[9px] text-muted">{label}</div>
      <div className={`mt-0.5 truncate text-[11px] font-medium ${color}`} title={value}>{value}</div>
    </div>
  )
}

function SummaryAction({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-border/40 bg-surface/30 px-2 py-1.5">
      <div className="text-[9px] text-muted">{label}</div>
      <div className="mt-0.5 text-[10px] leading-relaxed text-foreground">{value}</div>
    </div>
  )
}

function SummaryList({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div>
      <div className="mb-0.5 text-[10px] font-medium text-secondary">{title}</div>
      <ul className={`space-y-0.5 text-[10px] leading-relaxed ${tone}`}>
        {items.map((item, index) => <li key={`${title}-${index}`}>• {item}</li>)}
      </ul>
    </div>
  )
}

function buildDecisionSummary(
  rows: KlineRow[],
  levels: Record<LevelType, PriceLevel[]>,
  chan: StockChanAnalysis | undefined,
  close: number,
): DecisionSummaryData {
  const latest = rows.at(-1)
  const previous = rows.at(-2)
  const changePct = finiteNumber(latest?.change_pct)
    ?? (previous?.close ? ((close - previous.close) / previous.close) * 100 : null)
  const ma20 = finiteNumber(latest?.ma20) ?? latestSeriesValue(chan?.moving_averages?.ma20)
  const ma60 = finiteNumber(latest?.ma60) ?? latestSeriesValue(chan?.moving_averages?.ma60)
  const macdHist = finiteNumber(latest?.macd_hist) ?? latestSeriesValue(chan?.macd?.hist)
  const rsi = finiteNumber(latest?.rsi_14) ?? latestSeriesValue(chan?.rsi?.values)
  const volumeRatio = finiteNumber(latest?.vol_ratio_5d) ?? recentVolumeRatio(rows)
  const turnover = finiteNumber(latest?.turnover_rate)
  const lastBi = chan?.current?.last_bi
  const lastCbsp = chan?.current?.last_cbsp ?? null
  const recentDates = new Set(rows.slice(-30).map(item => item.date))
  const activeCbsp = lastCbsp && recentDates.has(lastCbsp.date) ? lastCbsp : null
  const mainFlow = firstFiniteField(latest, [
    'main_net_inflow',
    'fund_flow_net_inflow',
    'net_inflow',
    'large_order_net_inflow',
  ])

  let trendScore = 0
  if (ma20 != null) trendScore += close >= ma20 ? 2 : -2
  if (ma60 != null) trendScore += close >= ma60 ? 2 : -2
  if (ma20 != null && ma60 != null) trendScore += ma20 >= ma60 ? 1 : -1
  if (macdHist != null) trendScore += macdHist >= 0 ? 1 : -1
  if (lastBi) trendScore += lastBi.direction === 'up' ? 2 : -2
  const higherDirections = Object.values(chan?.multi_level ?? {})
    .map(item => item.current?.last_bi?.direction)
    .filter((value): value is 'up' | 'down' => value === 'up' || value === 'down')
  if (higherDirections.length > 0) {
    const higherUp = higherDirections.filter(value => value === 'up').length
    trendScore += higherUp >= Math.ceil(higherDirections.length / 2) ? 1 : -1
  }
  const trend = trendScore >= 5 ? '强势上行' : trendScore >= 2 ? '偏强' : trendScore <= -5 ? '弱势下行' : trendScore <= -2 ? '偏弱' : '震荡'
  const trendTone: SummaryTone = trendScore >= 2 ? 'bull' : trendScore <= -2 ? 'bear' : 'neutral'

  const volumeText = volumeRatio == null
    ? '量能未知'
    : volumeRatio >= 1.5
      ? `明显放量 ${volumeRatio.toFixed(2)}x`
      : volumeRatio >= 1.2
        ? `温和放量 ${volumeRatio.toFixed(2)}x`
        : volumeRatio <= 0.8
          ? `明显缩量 ${volumeRatio.toFixed(2)}x`
          : `量能平稳 ${volumeRatio.toFixed(2)}x`
  const fundsTone: SummaryTone = mainFlow != null
    ? mainFlow > 0 ? 'bull' : mainFlow < 0 ? 'bear' : 'neutral'
    : volumeRatio == null || volumeRatio < 0.8
    ? 'neutral'
    : changePct != null && changePct > 0 && volumeRatio >= 1.1
      ? 'bull'
      : changePct != null && changePct < 0 && volumeRatio >= 1.1
        ? 'bear'
        : 'neutral'
  const fundsSource = mainFlow != null
    ? `主力${mainFlow >= 0 ? '净流入' : '净流出'} ${formatAmount(mainFlow)}`
    : `量价代理${turnover != null ? ` · 换手 ${turnover.toFixed(2)}%` : ''}`
  const funds = fundsTone === 'bull'
    ? `资金偏强 · ${fundsSource} · ${volumeText}`
    : fundsTone === 'bear'
      ? `资金偏弱 · ${fundsSource} · ${volumeText}`
      : `资金观望 · ${fundsSource} · ${volumeText}`

  let emotionScore = 50
  if (changePct != null) emotionScore += changePct > 0 ? 8 : changePct < 0 ? -8 : 0
  if (rsi != null) emotionScore += rsi >= 55 && rsi <= 72 ? 10 : rsi < 35 ? -10 : rsi > 78 ? -8 : 0
  if (volumeRatio != null) emotionScore += volumeRatio >= 1.2 ? 7 : volumeRatio <= 0.8 ? -5 : 0
  if (activeCbsp) emotionScore += activeCbsp.side === 'buy' ? 12 : -12
  const emotion = emotionScore >= 68 ? '偏暖' : emotionScore >= 55 ? '略偏强' : emotionScore <= 32 ? '偏冷' : emotionScore <= 45 ? '略偏弱' : '中性'
  const emotionTone: SummaryTone = emotionScore >= 55 ? 'bull' : emotionScore <= 45 ? 'bear' : 'neutral'

  const buyConfirmed = activeCbsp?.side === 'buy'
  const sellConfirmed = activeCbsp?.side === 'sell'
  const newPosition = sellConfirmed || trendScore <= -2
    ? '暂不建仓，等待止跌和重新站回关键位'
    : buyConfirmed && trendScore >= 2
      ? '可小仓试探，回踩不破再考虑增加'
      : '等待突破或回踩确认，不追涨杀跌'
  const holding = sellConfirmed || trendScore <= -4
    ? '减仓防守，跌破支撑且放量时优先控制风险'
    : buyConfirmed && trendScore >= 3
      ? '持仓为主，回踩支撑不破且放量修复可考虑加仓'
      : '持有观察，未出现足够强的加仓确认'
  const bias = sellConfirmed || trendScore <= -4
    ? '偏空，优先防守'
    : buyConfirmed && trendScore >= 3
      ? '偏多，等待确认'
      : trendScore >= 2
        ? '偏多但不追高'
        : trendScore <= -2
          ? '偏弱，暂不激进'
          : '震荡，等待信号'
  const biasTone: SummaryTone = sellConfirmed || trendScore <= -2
    ? 'bear'
    : buyConfirmed || trendScore >= 2
      ? 'bull'
      : 'neutral'

  const allLevels = Object.values(levels)
    .flat()
    .filter((item, index, all) => all.findIndex(other => other.type === item.type && other.value === item.value) === index)
  const supports = allLevels.filter(item => item.side === 'support')
  const resistances = allLevels.filter(item => item.side === 'resistance')
  const nearestSupport = supports
    .filter(item => item.value <= close)
    .sort((a, b) => b.value - a.value)[0] ?? supports.sort((a, b) => Math.abs(a.value - close) - Math.abs(b.value - close))[0]
  const nearestResistance = resistances
    .filter(item => item.value >= close)
    .sort((a, b) => a.value - b.value)[0] ?? resistances.sort((a, b) => Math.abs(a.value - close) - Math.abs(b.value - close))[0]
  const summaryLevels = [nearestSupport, nearestResistance]
    .filter((item): item is PriceLevel => Boolean(item))
    .map(item => {
      const direction = item.side === 'support' ? 'support' as const : 'resistance' as const
      const distancePct = ((item.value - close) / close) * 100
      const absDistance = Math.abs(distancePct)
      const advice = direction === 'support'
        ? close < item.value
          ? '当前已跌破，反抽不能重新站稳时偏防守'
          : absDistance <= 1.5
            ? '回踩不破且缩量止跌可观察，放量跌破则减仓'
            : '回踩到此位先看承接，出现买点再考虑试探'
        : close > item.value
          ? '已突破，回踩不破并保持量能才考虑加仓'
          : absDistance <= 1.5
            ? '放量收盘突破并站稳才加仓，不突破不追高'
            : '作为上方目标位，接近时观察冲高回落和量价背离'
      return { level: item, direction, distancePct, advice }
    })

  const reasons = [
    `趋势${trend}：${ma20 != null ? `当前价${close >= ma20 ? '站上' : '低于'}MA20` : 'MA20暂无'}，${ma60 != null ? `${close >= ma60 ? '站上' : '低于'}MA60` : 'MA60暂无'}`,
    `资金${mainFlow != null ? `包含主力净流入字段 ${formatAmount(mainFlow)}` : '未提供主力净流入，使用量价代理'}：${volumeText}${turnover != null ? `，换手 ${turnover.toFixed(2)}%` : ''}`,
    `个股情绪${emotion}${rsi != null ? `，RSI ${rsi.toFixed(1)}` : ''}${activeCbsp ? `，近30个交易日出现${activeCbsp.label}` : ''}`,
  ]
  const risks = [
    nearestResistance ? `收盘不能有效突破 ${nearestResistance.value.toFixed(2)}，不宜仅凭盘中上冲追价` : '上方压力位数据不足',
    nearestSupport ? `跌破 ${nearestSupport.value.toFixed(2)} 且放量时，当前判断失效` : '下方支撑位数据不足',
    mainFlow == null ? '当前未提供主力净流入字段，量价代理不等同于真实主力资金流向' : '主力资金字段仍需结合连续多个交易日，单日净流入不能单独确认趋势',
  ]
  return {
    bias, biasTone, newPosition, holding, trend, trendTone, funds, fundsTone, emotion, emotionTone,
    levels: summaryLevels, reasons, risks,
  }
}

function finiteNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function firstFiniteField(row: KlineRow | undefined, fields: string[]): number | null {
  if (!row) return null
  for (const field of fields) {
    const value = finiteNumber(row[field])
    if (value != null) return value
  }
  return null
}

function formatAmount(value: number): string {
  const absolute = Math.abs(value)
  if (absolute >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (absolute >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(0)
}

function latestSeriesValue(values: (number | null)[] | undefined): number | null {
  if (!values) return null
  for (let index = values.length - 1; index >= 0; index -= 1) {
    const value = finiteNumber(values[index])
    if (value != null) return value
  }
  return null
}

function recentVolumeRatio(rows: KlineRow[]): number | null {
  const latestVolume = finiteNumber(rows.at(-1)?.volume)
  if (latestVolume == null || rows.length < 6) return null
  const previous = rows
    .slice(-6, -1)
    .map(item => finiteNumber(item.volume))
    .filter((value): value is number => value != null)
  if (previous.length === 0) return null
  const average = previous.reduce((sum, value) => sum + value, 0) / previous.length
  return average > 0 ? latestVolume / average : null
}

interface WyckoffEvent {
  date: string
  price: number
  side: 'buy' | 'sell' | 'neutral'
  type: 'SC' | 'Spring' | 'SOS' | 'UTAD' | 'SOW'
  label: string
}

function buildWyckoffEvents(rows: KlineRow[]): WyckoffEvent[] {
  const events: WyckoffEvent[] = []
  const window = 20

  for (let index = window; index < rows.length; index += 1) {
    const row = rows[index]
    const history = rows.slice(index - window, index)
    const high = finiteNumber(row.high)
    const low = finiteNumber(row.low)
    const open = finiteNumber(row.open)
    const close = finiteNumber(row.close)
    const volume = finiteNumber(row.volume)
    const highs = history.map(item => finiteNumber(item.high)).filter((value): value is number => value != null)
    const lows = history.map(item => finiteNumber(item.low)).filter((value): value is number => value != null)
    const volumes = history.map(item => finiteNumber(item.volume)).filter((value): value is number => value != null)
    if (
      high == null || low == null || open == null || close == null || volume == null
      || highs.length < window || lows.length < window || volumes.length < window
    ) continue

    const resistance = Math.max(...highs)
    const support = Math.min(...lows)
    const averageVolume = volumes.reduce((sum, value) => sum + value, 0) / volumes.length
    const averageSpread = history.reduce((sum, item) => {
      const itemHigh = finiteNumber(item.high)
      const itemLow = finiteNumber(item.low)
      return sum + (itemHigh != null && itemLow != null ? itemHigh - itemLow : 0)
    }, 0) / window
    const spread = high - low
    const volumeRatio = averageVolume > 0 ? volume / averageVolume : 0
    const closePosition = spread > 0 ? (close - low) / spread : 0.5
    const add = (type: WyckoffEvent['type'], side: WyckoffEvent['side'], price: number) => {
      events.push({ date: row.date, price, side, type, label: `${type} 威科夫候选事件` })
    }

    if (
      close < open
      && spread >= averageSpread * 1.5
      && volumeRatio >= 1.8
      && closePosition <= 0.35
      && low <= support * 1.03
    ) add('SC', 'neutral', low)

    if (
      low < support * 0.995
      && close > support
      && close > open
      && volumeRatio <= 1.3
    ) add('Spring', 'buy', low)

    if (close > resistance && close > open && volumeRatio >= 1.3) {
      add('SOS', 'buy', close)
    }

    if (high > resistance * 1.005 && close < resistance && volumeRatio >= 1.2) {
      add('UTAD', 'sell', high)
    }

    if (close < support && volumeRatio >= 1.3) add('SOW', 'sell', close)
  }

  return events.slice(-80)
}

// ===== 工具:收集要画的水平价位线(按开启的组 + 档位 + 强度配色) =====
// 注意:带状指标(布林带/Keltner/ATR)改用曲线渲染,不在此画水平线,避免重复。
function collectPriceLines(
  levels: Record<LevelType, PriceLevel[]> | undefined,
  active: Set<LevelType>,
  pivotRank: 1 | 2 | 3,
): { value: number; label: string; color: string; type: string }[] {
  if (!levels) return []
  const out: { value: number; label: string; color: string; type: string }[] = []
  for (const g of LEVEL_GROUPS) {
    if (!active.has(g.key)) continue
    for (const p of levels[g.key] ?? []) {
      // 枢轴点:按档位过滤(rank>P 的,只显示到选定的档位)
      if (p.type === 'pivot' && p.rank !== undefined && p.rank > pivotRank) continue
      // 波动通道类(boll / keltner三档 / atr_stop)整组走曲线渲染,不画水平线;
      // sr 组现为成交密集区水平点,直接画线即可,无需特判。
      if (p.type === 'boll' || p.type === 'keltner_s' || p.type === 'keltner_m'
          || p.type === 'keltner_l' || p.type === 'atr_stop') continue
      out.push({ value: p.value, label: p.label, color: strengthColor(p.strength, g.color), type: p.type })
    }
  }
  return out
}

function strengthColor(strength: string | undefined, base: string): string {
  // strong 用实色,medium 用 0.85,weak 用 0.55 透明
  if (strength === 'weak') return base + '8C'
  if (strength === 'medium') return base + 'D9'
  return base
}

/** 价位唯一标识: 同类型同价格视为同一点位(用于联动高亮)。 */
function levelKey(type: string, value: number): string {
  return `${type}-${value.toFixed(2)}`
}

function fmtVol(v: number): string {
  if (!v) return '0'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(0) + '万'
  return v.toFixed(0)
}

function timeframeLabel(value: string): string {
  if (value === '1d') return '日线'
  if (value === '1w') return '周线'
  if (value === '1M') return '月线'
  return value
}
