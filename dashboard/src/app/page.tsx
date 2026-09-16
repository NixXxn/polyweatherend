"use client";

import { useCallback, useEffect, useState, useTransition } from "react";
import {
  API_URL,
  csvExportUrl,
  fetchSnapshot,
  polymarketUrl,
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

function MarketLink({
  href,
  label = "Polymarket",
}: {
  href: string;
  label?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="pm-link text-[11px]"
      onClick={(e) => e.stopPropagation()}
    >
      {label} ↗
    </a>
  );
}

export default function OpsDashboard() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const [tab, setTab] = useState<"cities" | "positions" | "fills" | "skips">(
    "cities",
  );

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
    const id = setInterval(reload, 3000);
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
  const cities = snap?.cities ?? [];
  const positions = snap?.positions ?? [];
  const fills = snap?.fills ?? [];
  const skips = snap?.skips ?? [];
  const settlements = snap?.settlements ?? [];
  const hitRate =
    (status?.wins ?? 0) + (status?.losses ?? 0) > 0
      ? (
          ((status?.wins ?? 0) /
            ((status?.wins ?? 0) + (status?.losses ?? 0))) *
          100
        ).toFixed(0)
      : null;

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col gap-5 px-4 pb-14 pt-6">
      <header className="anim-rise flex items-start justify-between gap-3">
        <div>
          <h1 className="text-[1.65rem] font-semibold leading-none tracking-tight text-[var(--accent)]">
            WeatherBuyEnd
          </h1>
          <p className="mt-2 text-sm text-[var(--muted)]">
            Late-day METAR BUY NO · ops
          </p>
        </div>
        <div className="text-right text-[11px] text-[var(--muted)]">
          <div className="mono font-medium uppercase tracking-wide text-[var(--ink)]">
            {status?.mode ?? "…"}
          </div>
          <div className="mono mt-0.5">
            {status?.mock_markets ? "mock books" : "live books"}
          </div>
        </div>
      </header>

      {error && (
        <div className="anim-rise rounded-2xl border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3.5 py-2.5 text-sm text-[var(--danger)]">
          {error}
          <div className="mono mt-1 text-[11px] opacity-75">{API_URL || "/"}</div>
        </div>
      )}

      <section
        className={`anim-rise rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-4 ${armed ? "armed-glow" : ""}`}
      >
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted)]">
              Sleeve
            </div>
            <div
              className={`mt-1.5 text-2xl font-semibold tracking-tight ${armed ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
            >
              {armed ? "ARMED" : "FLAT"}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted)]">
              PnL today
            </div>
            <div
              className={`mono mt-1.5 text-2xl font-medium ${(status?.pnl_today ?? 0) >= 0 ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
            >
              {money(status?.pnl_today)}
            </div>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-4 gap-2">
          {[
            ["Open", status?.open_no_count ?? "—"],
            ["W/L", `${status?.wins ?? 0}/${status?.losses ?? 0}`],
            [
              "Hit",
              hitRate != null ? `${hitRate}%` : "—",
            ],
            [
              "METAR",
              status?.metar_age_worst_min != null
                ? `${Math.round(status.metar_age_worst_min)}m`
                : "—",
            ],
          ].map(([label, value]) => (
            <div
              key={label}
              className="rounded-xl bg-[var(--bg)]/80 px-2 py-2.5 text-center"
            >
              <div className="text-[10px] font-medium uppercase tracking-wide text-[var(--muted)]">
                {label}
              </div>
              <div className="mono mt-1 text-[15px] font-semibold">{value}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="anim-rise rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold">Controls</h2>
          <a
            href={csvExportUrl("all")}
            className="tap rounded-lg bg-[var(--accent-soft)] px-3 py-1.5 text-xs font-semibold text-[var(--accent)]"
          >
            Export CSV
          </a>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <button
            disabled={pending}
            onClick={() =>
              run(() => postControl("/api/controls/kill", { reason: "manual" }))
            }
            className="tap min-h-12 rounded-xl bg-[var(--danger)] px-3 text-sm font-semibold text-white"
          >
            Kill all
          </button>
          <button
            disabled={pending}
            onClick={() => run(() => postControl("/api/controls/arm"))}
            className="tap min-h-12 rounded-xl bg-[var(--accent)] px-3 text-sm font-semibold text-white"
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
            className="tap min-h-12 rounded-xl border border-[var(--line)] bg-[var(--bg)] px-3 text-sm font-medium"
          >
            Sleeve {snap?.controls?.sleeve_no_eliminated ? "ON" : "OFF"}
          </button>
          <button
            disabled={pending}
            onClick={() => {
              const next = (snap?.controls?.stake_multiplier ?? 1) >= 2 ? 1 : 2;
              run(() =>
                postControl("/api/controls/stake", { multiplier: next }),
              );
            }}
            className="tap min-h-12 rounded-xl border border-[var(--line)] bg-[var(--bg)] px-3 text-sm font-medium"
          >
            Stake ×{snap?.controls?.stake_multiplier ?? 1}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {(["all", "trades", "skips", "wins", "losses"] as const).map((k) => (
            <a
              key={k}
              href={csvExportUrl(k)}
              className="tap rounded-md border border-[var(--line)] px-2.5 py-1 text-[11px] text-[var(--muted)]"
            >
              {k}.csv
            </a>
          ))}
        </div>
        {status?.kill_reason ? (
          <p className="mt-3 text-xs text-[var(--danger)]">
            Kill: {status.kill_reason}
          </p>
        ) : null}
      </section>

      <nav className="anim-rise flex gap-1 rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] p-1">
        {(
          [
            ["cities", "Cities", cities.length],
            ["positions", "Pos", positions.length],
            ["fills", "Fills", fills.length],
            ["skips", "Skips", skips.length],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`tap flex-1 rounded-lg px-1.5 py-2.5 text-[11px] font-semibold ${
              tab === id
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--muted)]"
            }`}
          >
            {label}
            <span className="mono ml-1 opacity-80">{count}</span>
          </button>
        ))}
      </nav>

      {tab === "cities" && (
        <section className="flex flex-col gap-2.5">
          {cities.length === 0 && (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-8 text-center text-sm text-[var(--muted)]">
              Waiting for METAR / market loop…
            </div>
          )}
          {cities
            .slice()
            .sort((a, b) => {
              const rank = (x: string) =>
                ({ ELIM: 0, WATCH: 1, BLOCKED: 2, IDLE: 3 })[x] ?? 9;
              return rank(a.badge) - rank(b.badge);
            })
            .map((c, i) => (
              <article
                key={c.location_id}
                className="anim-rise rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-3"
                style={{ animationDelay: `${Math.min(i, 8) * 30}ms` }}
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <div className="font-semibold capitalize tracking-tight">
                      {c.city_slug.replace(/-/g, " ")}
                    </div>
                    <div className="mono mt-0.5 text-[11px] text-[var(--muted)]">
                      {c.icao}
                      {c.hours_to_noon != null
                        ? ` · ${c.hours_to_noon > 0 ? `${c.hours_to_noon}h to noon` : `${Math.abs(c.hours_to_noon)}h past noon`}`
                        : ""}
                    </div>
                  </div>
                  <span
                    className={`rounded-md px-2 py-1 text-[10px] font-bold tracking-wider ${badgeClass(c.badge)}`}
                  >
                    {c.badge}
                  </span>
                </div>
                <div className="mono mt-2.5 grid grid-cols-3 gap-2 text-[11px] text-[var(--muted)]">
                  <div>
                    tmax{" "}
                    <span className="font-medium text-[var(--ink)]">
                      {c.tmax_so_far != null ? c.tmax_so_far.toFixed(1) : "—"}
                    </span>
                  </div>
                  <div>
                    NO{" "}
                    <span className="font-medium text-[var(--ink)]">
                      {c.best_no != null ? c.best_no.toFixed(3) : "—"}
                    </span>
                  </div>
                  <div>
                    age{" "}
                    <span className="font-medium text-[var(--ink)]">
                      {c.metar_age_minutes != null
                        ? `${c.metar_age_minutes.toFixed(0)}m`
                        : "—"}
                    </span>
                  </div>
                </div>
              </article>
            ))}
        </section>
      )}

      {tab === "positions" && (
        <section className="flex flex-col gap-2.5">
          {positions.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-6 text-center text-sm text-[var(--muted)]">
              No open NO positions
            </div>
          ) : (
            positions.map((p) => {
              const href = polymarketUrl({
                city: p.city,
                kind: p.kind,
                end_date: p.end_date,
                url: p.polymarket_url,
              });
              return (
                <div
                  key={p.market_id}
                  className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold capitalize tracking-tight">
                        {p.city.replace(/_/g, " ")}
                      </div>
                      <div className="mt-1">
                        <MarketLink href={href} />
                      </div>
                    </div>
                    <div
                      className={`mono text-sm font-medium ${(p.unrealized_pnl ?? 0) >= 0 ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
                    >
                      {money(p.unrealized_pnl)}
                    </div>
                  </div>
                  <div className="mono mt-2 text-[11px] text-[var(--muted)]">
                    entry {p.entry_price.toFixed(3)} · mark{" "}
                    {p.mark_no.toFixed(3)} · ${p.size_usd.toFixed(2)}
                  </div>
                </div>
              );
            })
          )}
          {settlements.length > 0 && (
            <>
              <h3 className="mt-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
                Settlements
              </h3>
              {settlements.slice(0, 20).map((s, i) => {
                const href = polymarketUrl({
                  city: s.city || s.location_id,
                  url: s.polymarket_url,
                });
                return (
                  <div
                    key={s.settlement_id || i}
                    className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-2.5"
                  >
                    <div className="flex items-start justify-between gap-2 text-sm">
                      <div>
                        <span className="font-semibold capitalize">
                          {(s.city || s.location_id || "").replace(/_/g, " ")}
                        </span>
                        <div className="mt-1">
                          <MarketLink href={href} />
                        </div>
                      </div>
                      <span
                        className={`mono font-medium ${s.result === "win" ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
                      >
                        {s.result} {money(s.pnl_usd)}
                      </span>
                    </div>
                    {s.reason ? (
                      <div className="mono mt-1 text-[10px] text-[var(--muted)]">
                        {s.reason}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </>
          )}
        </section>
      )}

      {tab === "fills" && (
        <section className="flex flex-col gap-2.5">
          {fills.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-6 text-center text-sm text-[var(--muted)]">
              No fills yet
            </div>
          ) : (
            fills.slice(0, 50).map((f) => {
              const href = polymarketUrl({
                city: f.city || f.location_id,
                url: f.polymarket_url,
              });
              return (
                <div
                  key={f.fill_id}
                  className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-2.5"
                >
                  <div className="flex items-start justify-between gap-2 text-sm">
                    <div>
                      <span className="font-semibold capitalize">
                        {(f.city || f.location_id || "").replace(/_/g, " ")}
                      </span>
                      <div className="mt-1">
                        <MarketLink href={href} />
                      </div>
                    </div>
                    <span className="mono font-medium">
                      {f.price.toFixed(3)} · ${f.size_usd.toFixed(2)}
                    </span>
                  </div>
                  <div className="mono mt-1.5 text-[11px] text-[var(--muted)]">
                    {f.status} · {f.mode} · {f.latency_ms?.toFixed?.(0) ?? "—"}
                    ms · {new Date(f.ts).toLocaleTimeString()}
                  </div>
                </div>
              );
            })
          )}
        </section>
      )}

      {tab === "skips" && (
        <section className="flex flex-col gap-2.5">
          {skips.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-6 text-center text-sm text-[var(--muted)]">
              No skips logged
            </div>
          ) : (
            skips.slice(0, 50).map((s, i) => (
              <div
                key={s.skip_id || i}
                className="rounded-xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-2.5"
              >
                <div className="flex justify-between gap-2 text-sm">
                  <span className="font-semibold capitalize">
                    {(s.city || s.location_id || "").replace(/-/g, " ")}
                  </span>
                  <span className="mono text-[11px] text-[var(--muted)]">
                    {s.reason}
                  </span>
                </div>
                <div className="mono mt-1 text-[11px] text-[var(--muted)]">
                  {s.no_price != null
                    ? `NO ${Number(s.no_price).toFixed(3)} · `
                    : ""}
                  {new Date(s.ts).toLocaleTimeString()}
                </div>
              </div>
            ))
          )}
        </section>
      )}
    </main>
  );
}
