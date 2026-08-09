import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesPrimitive,
  type IPrimitivePaneView,
  type IPrimitivePaneRenderer,
  type SeriesAttachedParameter,
  type Time,
  type CandlestickData,
  type SeriesMarker,
  type ISeriesMarkersPluginApi,
} from "lightweight-charts";
import { API_BASE } from "../api/client";
import type { ActiveTrade } from "../api/types";

interface Props {
  symbol: string | null;
  position: ActiveTrade | null;
}

type CandleRow = CandlestickData<Time>;

/**
 * Own chart: Long/Short position zones in series coordinates (track zoom).
 */
export function TradingViewPanel({ symbol, position }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const primitiveRef = useRef<PositionPrimitive | null>(null);
  const markersApiRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const candleTimesRef = useRef<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!symbol || !wrapRef.current) return;
    const el = wrapRef.current;
    setError(null);
    setLoading(true);

    const chart = createChart(el, {
      width: Math.max(el.clientWidth, 100),
      height: Math.max(el.clientHeight, 240),
      layout: {
        background: { type: ColorType.Solid, color: "#0b0e14" },
        textColor: "#7c8494",
      },
      grid: {
        vertLines: { color: "#1a2030" },
        horzLines: { color: "#1a2030" },
      },
      rightPriceScale: { borderColor: "#232a3a" },
      timeScale: { borderColor: "#232a3a", timeVisible: true, secondsVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#33d18b",
      downColor: "#ff5d6c",
      borderVisible: false,
      wickUpColor: "#33d18b",
      wickDownColor: "#ff5d6c",
    });
    chartRef.current = chart;
    seriesRef.current = series;
    markersApiRef.current = createSeriesMarkers(series, []);

    const ro = new ResizeObserver(() => {
      if (!wrapRef.current || !chartRef.current) return;
      const { clientWidth: w, clientHeight: h } = wrapRef.current;
      if (w > 0 && h > 0) chartRef.current.resize(w, h);
    });
    ro.observe(el);
    // one frame later — flex layout often settles after mount
    requestAnimationFrame(() => {
      if (!wrapRef.current || !chartRef.current) return;
      const { clientWidth: w, clientHeight: h } = wrapRef.current;
      if (w > 0 && h > 0) chartRef.current.resize(w, h);
    });

    let cancelled = false;
    async function load() {
      try {
        const rows = await fetchKlines(symbol!);
        if (cancelled || !seriesRef.current) return;
        if (rows.length === 0) {
          setError("no candles returned");
          setLoading(false);
          return;
        }
        seriesRef.current.setData(rows);
        candleTimesRef.current = rows.map((r) => Number(r.time));
        chart.timeScale().fitContent();
        setError(null);
        setLoading(false);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), 30_000);

    return () => {
      cancelled = true;
      window.clearInterval(poll);
      ro.disconnect();
      if (primitiveRef.current) {
        series.detachPrimitive(primitiveRef.current);
        primitiveRef.current = null;
      }
      markersApiRef.current = null;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [symbol]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;

    if (primitiveRef.current) {
      series.detachPrimitive(primitiveRef.current);
      primitiveRef.current = null;
    }
    markersApiRef.current?.setMarkers([]);

    if (!position || position.closed || (symbol && position.symbol !== symbol)) {
      return;
    }

    const prim = new PositionPrimitive(position);
    series.attachPrimitive(prim);
    primitiveRef.current = prim;

    const opened = Math.floor(Date.parse(position.opened_at) / 1000);
    const times = candleTimesRef.current;
    let markerTime = times.length ? times[times.length - 1]! : opened;
    if (times.length) {
      let best = times[0]!;
      let bestDist = Math.abs(best - opened);
      for (const t of times) {
        const d = Math.abs(t - opened);
        if (d < bestDist) {
          best = t;
          bestDist = d;
        }
      }
      markerTime = best;
    }
    const markers: SeriesMarker<Time>[] = [
      {
        time: markerTime as Time,
        position: position.side === "LONG" ? "belowBar" : "aboveBar",
        color: position.side === "LONG" ? "#33d18b" : "#ff5d6c",
        shape: position.side === "LONG" ? "arrowUp" : "arrowDown",
        text: position.side === "LONG" ? "Long" : "Short",
      },
    ];
    try {
      markersApiRef.current?.setMarkers(markers);
    } catch {
      /* invalid marker time — zones still draw */
    }
  }, [
    position,
    symbol,
    position?.entry_price,
    position?.stop_price,
    position?.take_profit_price,
    position?.current_price,
    position?.side,
    position?.opened_at,
  ]);

  if (!symbol) {
    return (
      <div className="tv-panel tv-empty">
        <p className="muted">select a symbol to load its chart</p>
      </div>
    );
  }

  return (
    <div className="tv-panel">
      <div className="tv-chart-host" ref={wrapRef} />
      {loading && <div className="tv-chart-status muted">loading candles…</div>}
      {error && <div className="tv-chart-status topbar-error">chart: {error}</div>}
    </div>
  );
}

class PositionPrimitive implements ISeriesPrimitive<Time> {
  private _trade: ActiveTrade;
  private _series: ISeriesApi<"Candlestick"> | null = null;
  private readonly _paneView: PositionPaneView;

  constructor(trade: ActiveTrade) {
    this._trade = trade;
    this._paneView = new PositionPaneView(this);
  }

  trade() {
    return this._trade;
  }

  series() {
    return this._series;
  }

  attached({ series }: SeriesAttachedParameter<Time>) {
    this._series = series as ISeriesApi<"Candlestick">;
  }

  detached() {
    this._series = null;
  }

  paneViews() {
    return [this._paneView];
  }

  updateAllViews() {}
}

class PositionPaneView implements IPrimitivePaneView {
  private readonly _source: PositionPrimitive;
  private readonly _renderer = new PositionRenderer();

  constructor(source: PositionPrimitive) {
    this._source = source;
  }

  zOrder() {
    return "bottom" as const;
  }

  renderer() {
    const series = this._source.series();
    const trade = this._source.trade();
    if (!series) return null;
    const yEntry = series.priceToCoordinate(trade.entry_price);
    const yStop = series.priceToCoordinate(trade.stop_price);
    const yTp = series.priceToCoordinate(trade.take_profit_price);
    const yMark = series.priceToCoordinate(trade.current_price);
    if (yEntry == null || yStop == null || yTp == null) return null;
    this._renderer.update({
      yEntry,
      yStop,
      yTp,
      yMark,
      long: trade.side === "LONG",
      entry: trade.entry_price,
      stop: trade.stop_price,
      tp: trade.take_profit_price,
      mark: trade.current_price,
      r: trade.unrealized_r,
    });
    return this._renderer;
  }
}

interface DrawState {
  yEntry: number;
  yStop: number;
  yTp: number;
  yMark: number | null;
  long: boolean;
  entry: number;
  stop: number;
  tp: number;
  mark: number;
  r: number;
}

class PositionRenderer implements IPrimitivePaneRenderer {
  private _s: DrawState | null = null;

  update(s: DrawState) {
    this._s = s;
  }

  draw(target: {
    useBitmapCoordinateSpace: (
      fn: (scope: {
        context: CanvasRenderingContext2D;
        bitmapSize: { width: number; height: number };
        horizontalPixelRatio: number;
        verticalPixelRatio: number;
      }) => void,
    ) => void;
  }) {
    const s = this._s;
    if (!s) return;
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      const w = scope.bitmapSize.width;
      const hRatio = scope.verticalPixelRatio;
      const xRatio = scope.horizontalPixelRatio;
      const yE = s.yEntry * hRatio;
      const yS = s.yStop * hRatio;
      const yT = s.yTp * hRatio;
      const yM = s.yMark != null ? s.yMark * hRatio : null;

      ctx.fillStyle = "rgba(51, 209, 139, 0.16)";
      ctx.fillRect(0, Math.min(yE, yT), w, Math.abs(yT - yE));
      ctx.fillStyle = "rgba(255, 93, 108, 0.16)";
      ctx.fillRect(0, Math.min(yE, yS), w, Math.abs(yS - yE));

      const drawLevel = (y: number, color: string, label: string, price: number) => {
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, 2 * xRatio);
        ctx.setLineDash(label === "Mark" ? [] : [6 * xRatio, 4 * xRatio]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
        ctx.setLineDash([]);

        const tag = `${label} ${fmtPx(price)}`;
        ctx.font = `${Math.round(11 * hRatio)}px monospace`;
        const tw = ctx.measureText(tag).width + 10 * xRatio;
        const th = 16 * hRatio;
        const tx = w - tw - 8 * xRatio;
        const ty = y - th / 2;
        ctx.fillStyle = "rgba(11, 14, 20, 0.92)";
        ctx.fillRect(tx, ty, tw, th);
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, xRatio);
        ctx.strokeRect(tx, ty, tw, th);
        ctx.fillStyle = color;
        ctx.fillText(tag, tx + 5 * xRatio, y + 4 * hRatio);
      };

      drawLevel(yT, "#33d18b", "TP", s.tp);
      drawLevel(yE, "#4d9dff", s.long ? "Long" : "Short", s.entry);
      drawLevel(yS, "#ff5d6c", "Stop", s.stop);
      if (yM != null) drawLevel(yM, "#e6e9f0", "Mark", s.mark);

      const title = `${s.long ? "Long" : "Short"}  ${s.r >= 0 ? "+" : ""}${s.r.toFixed(2)}R`;
      ctx.font = `${Math.round(12 * hRatio)}px monospace`;
      const bw = ctx.measureText(title).width + 14 * xRatio;
      const bh = 20 * hRatio;
      ctx.fillStyle = "rgba(11, 14, 20, 0.9)";
      ctx.fillRect(8 * xRatio, 8 * hRatio, bw, bh);
      ctx.strokeStyle = s.long ? "#33d18b" : "#ff5d6c";
      ctx.strokeRect(8 * xRatio, 8 * hRatio, bw, bh);
      ctx.fillStyle = s.r >= 0 ? "#33d18b" : "#ff5d6c";
      ctx.fillText(title, 15 * xRatio, 22 * hRatio);
    });
  }
}

function fmtPx(n: number): string {
  if (n >= 1000) return n.toFixed(2);
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(6);
}

async function fetchKlines(symbol: string): Promise<CandleRow[]> {
  const url = `${API_BASE}/api/v1/candles/${encodeURIComponent(symbol)}?interval=1m&limit=300`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`klines ${resp.status}`);
  const raw = (await resp.json()) as {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
  }[];
  return raw.map((r) => ({
    time: r.time as Time,
    open: r.open,
    high: r.high,
    low: r.low,
    close: r.close,
  }));
}
