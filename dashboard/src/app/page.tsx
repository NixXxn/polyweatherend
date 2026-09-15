"use client";

import { useCallback, useEffect, useState, useTransition } from "react";
import {
  API_URL,
  fetchSnapshot,
  postControl,
  type Snapshot,
} from "@/lib/api";

function money(n: number | undefined | null) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}`;
}

function badgeClass(badge: string) {
  switch (badge) {
    case "ELIM":
      return "bg-[var(--ok-soft)] text-[var(--ok)]";
    case "WATCH":
      return "bg-[var(--warn-soft)] text-[var(--warn)]";
    case "BLOCKED":
      return "bg-[var(--danger-soft)] text-[var(--danger)]";
    default:
      return "bg-[var(--bg)] text-[var(--muted)]";
  }
}

export default function OpsDashboard() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const reload = useCallback(async () => {
    try {
      const data = await fetchSnapshot();
      setSnap(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "API unreachable");
    }
  }, []);

  useEffect(() => {
    reload();
    const id = setInterval(reload, 4000);
    return () => clearInterval(id);
  }, [reload]);

  const run = (fn: () => Promise<void>) => {
    startTransition(async () => {
      try {
        await fn();
        await reload();
      } catch (e) {
        setError(e instanceof Error ? e.message : "control failed");
      }
    });
  };

  const status = snap?.status;
  const armed = Boolean(status?.armed);

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col gap-4 px-4 pb-10 pt-5">
      <header className="flex items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-[var(--accent)] uppercase">
            WeatherBuyEnd
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Ops</h1>
        </div>
        <div className="text-right text-xs text-[var(--muted)]">
          <div className="mono">{status?.mode ?? "…"}</div>
          <div className="mono">{status?.mock_markets ? "mock books" : "live books"}</div>
        </div>
      </header>

      {error && (
        <div className="rounded-xl border border-[var(--danger)]/30 bg-[var(--danger-soft)] px-3 py-2 text-sm text-[var(--danger)]">
          {error}
          <div className="mono mt-1 text-[11px] opacity-80">{API_URL}</div>
        </div>
      )}

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-4 shadow-[0_1px_0_rgba(20,32,28,0.04)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-xs text-[var(--muted)]">Status</div>
            <div
              className={`mt-1 text-xl font-semibold ${armed ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
            >
              {armed ? "ARMED" : "FLAT / KILLED"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-[var(--muted)]">PnL today</div>
            <div className="mono mt-1 text-xl font-medium">
              {money(status?.pnl_today)}
            </div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-xl bg-[var(--bg)] px-2 py-2">
            <div className="text-[var(--muted)]">Open NO</div>
            <div className="mono mt-1 text-base font-medium">
              {status?.open_no_count ?? "—"}
            </div>
          </div>
          <div className="rounded-xl bg-[var(--bg)] px-2 py-2">
            <div className="text-[var(--muted)]">METAR age</div>
            <div className="mono mt-1 text-base font-medium">
              {status?.metar_age_worst_min != null
                ? `${status.metar_age_worst_min}m`
                : "—"}
            </div>
          </div>
          <div className="rounded-xl bg-[var(--bg)] px-2 py-2">
            <div className="text-[var(--muted)]">Venue err</div>
            <div className="mono mt-1 text-base font-medium">
              {status?.venue_error_rate != null
                ? `${(status.venue_error_rate * 100).toFixed(0)}%`
                : "—"}
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-4">
        <div className="mb-3 text-sm font-semibold">Controls</div>
        <div className="grid grid-cols-2 gap-2">
          <button
            disabled={pending}
            onClick={() => run(() => postControl("/api/controls/kill", { reason: "manual" }))}
            className="min-h-12 rounded-xl bg-[var(--danger)] px-3 text-sm font-semibold text-white active:scale-[0.98]"
          >
            Kill all
          </button>
          <button
            disabled={pending}
            onClick={() => run(() => postControl("/api/controls/arm"))}
            className="min-h-12 rounded-xl bg-[var(--accent)] px-3 text-sm font-semibold text-white active:scale-[0.98]"
          >
            Arm
          </button>
          <button
            disabled={pending}
            onClick={() =>
              run(() =>
                postControl("/api/controls/sleeve", {
                  enabled: !snap?.controls?.sleeve_no_eliminated,
                }),
              )
            }
            className="min-h-12 rounded-xl border border-[var(--line)] bg-[var(--bg)] px-3 text-sm font-medium active:scale-[0.98]"
          >
            Sleeve {snap?.controls?.sleeve_no_eliminated ? "ON" : "OFF"}
          </button>
          <button
            disabled={pending}
            onClick={() => {
              const next =
                (snap?.controls?.stake_multiplier ?? 1) >= 2 ? 1 : 2;
              run(() => postControl("/api/controls/stake", { multiplier: next }));
            }}
            className="min-h-12 rounded-xl border border-[var(--line)] bg-[var(--bg)] px-3 text-sm font-medium active:scale-[0.98]"
          >
            Stake ×{snap?.controls?.stake_multiplier ?? 1}
          </button>
        </div>
        {status?.kill_reason ? (
          <p className="mt-3 text-xs text-[var(--danger)]">
            Kill reason: {status.kill_reason}
          </p>
        ) : null}
      </section>

      <section>
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Cities</h2>
          <span className="mono text-xs text-[var(--muted)]">
            {status?.cities_tracked ?? 0} tracked
          </span>
        </div>
        <div className="flex flex-col gap-2">
          {(snap?.cities ?? []).length === 0 && (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-6 text-center text-sm text-[var(--muted)]">
              Waiting for METAR / market loop…
            </div>
          )}
          {(snap?.cities ?? [])
            .slice()
            .sort((a, b) => {
              const rank = (x: string) =>
                ({ ELIM: 0, WATCH: 1, BLOCKED: 2, IDLE: 3 }[x] ?? 9);
              return rank(a.badge) - rank(b.badge);
            })
            .map((c) => (
              <article
                key={c.location_id}
                className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3 py-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-semibold capitalize">
                      {c.city_slug.replace(/-/g, " ")}
                    </div>
                    <div className="mono text-[11px] text-[var(--muted)]">
                      {c.icao} · {c.hours_to_noon != null ? `${c.hours_to_noon}h→noon` : "—"}
                    </div>
                  </div>
                  <span
                    className={`rounded-md px-2 py-1 text-[11px] font-semibold tracking-wide ${badgeClass(c.badge)}`}
                  >
                    {c.badge}
                  </span>
                </div>
                <div className="mono mt-2 grid grid-cols-3 gap-2 text-[11px] text-[var(--muted)]">
                  <div>
                    tmax{" "}
                    <span className="text-[var(--ink)]">
                      {c.tmax_so_far != null ? c.tmax_so_far.toFixed(1) : "—"}
                    </span>
                  </div>
                  <div>
                    NO{" "}
                    <span className="text-[var(--ink)]">
                      {c.best_no != null ? c.best_no.toFixed(3) : "—"}
                    </span>
                  </div>
                  <div>
                    age{" "}
                    <span className="text-[var(--ink)]">
                      {c.metar_age_minutes != null
                        ? `${c.metar_age_minutes.toFixed(0)}m`
                        : "—"}
                    </span>
                  </div>
                </div>
                {c.reason && c.badge !== "ELIM" ? (
                  <div className="mt-1 text-[11px] text-[var(--muted)]">{c.reason}</div>
                ) : null}
              </article>
            ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Positions</h2>
        {(snap?.positions ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-5 text-center text-sm text-[var(--muted)]">
            No open NO positions
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {snap!.positions.map((p) => (
              <div
                key={p.market_id}
                className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3 py-3"
              >
                <div className="flex justify-between gap-2">
                  <div className="font-medium capitalize">
                    {p.city.replace(/_/g, " ")}
                  </div>
                  <div className="mono text-sm">{money(p.unrealized_pnl)}</div>
                </div>
                <div className="mono mt-1 text-[11px] text-[var(--muted)]">
                  entry {p.entry_price.toFixed(3)} · mark {p.mark_no.toFixed(3)} · $
                  {p.size_usd.toFixed(2)} · {p.mode}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold">Fills</h2>
        {(snap?.fills ?? []).length === 0 ? (
          <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-5 text-center text-sm text-[var(--muted)]">
            No fills yet
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {snap!.fills.slice(0, 50).map((f) => (
              <div
                key={f.fill_id}
                className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3 py-2"
              >
                <div className="flex justify-between text-sm">
                  <span className="font-medium">{f.location_id}</span>
                  <span className="mono">
                    {f.price.toFixed(3)} · ${f.size_usd.toFixed(2)}
                  </span>
                </div>
                <div className="mono text-[11px] text-[var(--muted)]">
                  {f.status} · {f.mode} · {f.latency_ms.toFixed(0)}ms ·{" "}
                  {new Date(f.ts).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
