export type Snapshot = {
  status: {
    armed?: boolean;
    killed?: boolean;
    kill_reason?: string;
    mode?: string;
    mock_markets?: boolean;
    open_no_count?: number;
    pnl_today?: number;
    realized_pnl?: number;
    unrealized_pnl?: number;
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
    daily_notional?: number;
    markets_today?: number;
  };
  pnl: {
    realized?: number;
    unrealized?: number;
    today?: number;
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
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");

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
