export type Snapshot = {
  status: {
    armed?: boolean;
    killed?: boolean;
    kill_reason?: string;
    mode?: string;
    live_clob?: boolean;
    mock_markets?: boolean;
    budget_usd?: number;
    effective_budget_usd?: number;
    wallet_usd?: number | null;
    wallet_allowance_usd?: number | null;
    wallet_error?: string | null;
    poly_sig_type?: number;
    poly_funder_set?: boolean;
    fills_paper?: number;
    fills_live?: number;
    live_order_attempts?: number;
    live_order_ok?: number;
    open_no_count?: number;
    gains_usd?: number;
    pnl_today?: number;
    realized_pnl?: number;
    unrealized_pnl?: number;
    open_notional?: number;
    deployable_usd?: number;
    max_deploy_frac?: number;
    cash_reserve_usd?: number;
    equity_usd?: number;
    wins?: number;
    losses?: number;
    metar_age_worst_min?: number | null;
    last_metar_ts?: string | null;
    last_book_ts?: string | null;
    venue_error_rate?: number;
    tick?: number;
    markets_tracked?: number;
    cities_tracked?: number;
    fills_count?: number;
    skips_count?: number;
    settlements_count?: number;
  };
  cities: CityRow[];
  positions: Position[];
  fills: Fill[];
  skips?: Skip[];
  settlements?: Settlement[];
  controls: {
    killed?: boolean;
    sleeve_no_eliminated?: boolean;
    stake_multiplier?: number;
    budget_usd?: number;
    open_notional?: number;
    deployable_usd?: number;
    max_deploy_frac?: number;
    gains_usd?: number;
    daily_notional?: number;
    markets_today?: number;
  };
  pnl: {
    budget_usd?: number;
    gains_usd?: number;
    realized?: number;
    unrealized?: number;
    today?: number;
    open_notional?: number;
    deployable_usd?: number;
    equity_usd?: number;
    wins?: number;
    losses?: number;
  };
};

export type CityRow = {
  location_id: string;
  city_slug: string;
  icao: string;
  badge: string;
  hours_to_noon: number | null;
  tmax_so_far: number | null;
  metar_age_minutes: number | null;
  eliminated: boolean;
  best_no: number | null;
  edge: number | null;
  markets: number;
  reason: string;
};

export type Position = {
  market_id: string;
  location_id: string;
  city: string;
  entry_price: number;
  size_usd: number;
  shares: number;
  mode: string;
  mark_no: number;
  unrealized_pnl: number;
  question: string;
  polymarket_url?: string;
  kind?: string;
  end_date?: string;
};

export type Fill = {
  fill_id: string;
  location_id: string;
  price: number;
  size_usd: number;
  latency_ms: number;
  mode: string;
  status: string;
  ts: string;
  question?: string;
  city?: string;
  polymarket_url?: string;
  market_id?: string;
};

export type Skip = {
  skip_id?: string;
  location_id: string;
  city?: string;
  reason: string;
  no_price?: number | null;
  ts: string;
  question?: string;
};

export type Settlement = {
  settlement_id?: string;
  location_id: string;
  city?: string;
  result: string;
  pnl_usd: number;
  entry_price: number;
  exit_price: number;
  ts: string;
  polymarket_url?: string;
  reason?: string;
  question?: string;
  mode?: string;
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

/** Polymarket event URL for a weather city/day (fallback when API omits link). */
export function polymarketUrl(opts: {
  city?: string;
  kind?: string;
  end_date?: string;
  url?: string | null;
}): string {
  if (opts.url) return opts.url;
  const city = (opts.city || "nyc").replace(/_/g, "-");
  const kind = (opts.kind || "highest").toLowerCase().startsWith("high")
    ? "highest"
    : "lowest";
  let datePart = "";
  if (opts.end_date) {
    const d = new Date(`${opts.end_date.slice(0, 10)}T12:00:00Z`);
    if (!Number.isNaN(d.getTime())) {
      const month = d.toLocaleString("en-US", {
        month: "long",
        timeZone: "UTC",
      }).toLowerCase();
      datePart = `${month}-${d.getUTCDate()}-${d.getUTCFullYear()}`;
    }
  }
  if (!datePart) {
    const now = new Date();
    const month = now
      .toLocaleString("en-US", { month: "long" })
      .toLowerCase();
    datePart = `${month}-${now.getDate()}-${now.getFullYear()}`;
  }
  return `https://polymarket.com/event/${kind}-temperature-in-${city}-on-${datePart}`;
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const res = await fetch(`${API_URL}/api/snapshot`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

export async function postControl(
  path: string,
  body?: Record<string, unknown>,
): Promise<void> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`Control ${res.status}`);
}

export function csvExportUrl(kind: string = "all"): string {
  return `${API_URL}/api/export?kind=${encodeURIComponent(kind)}`;
}

export { API_URL };
