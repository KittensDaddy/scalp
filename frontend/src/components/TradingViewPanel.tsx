interface Props {
  symbol: string | null;
}

/**
 * Free TradingView "Advanced Chart" widget embed, keyed BINANCE:{SYMBOL}.P
 * (SCANNER_DASHBOARD_PLAN.md §G). Bot overlays (entry/SL/TP/score) render in the
 * adjacent SymbolDetail panel instead of on the chart itself — the free embed
 * doesn't support programmatic drawings, and building a workaround around that
 * limitation is explicitly out of scope per the plan.
 */
export function TradingViewPanel({ symbol }: Props) {
  if (!symbol) {
    return (
      <div className="tv-panel tv-empty">
        <p className="muted">select a symbol to load its chart</p>
      </div>
    );
  }

  const src = `https://www.tradingview.com/widgetembed/?symbol=BINANCE:${symbol}.P&interval=1&theme=dark&style=1&hide_top_toolbar=0&hide_legend=0&saveimage=0`;

  return (
    <div className="tv-panel">
      <iframe
        key={symbol}
        title={`TradingView ${symbol}`}
        src={src}
        frameBorder={0}
        allowFullScreen
      />
    </div>
  );
}
