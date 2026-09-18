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

function usd(n: number | undefined | null) {
  if (n == null || Number.isNaN(n)) return "—";
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
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
  const [budgetDraft, setBudgetDraft] = useState("");
  const [editingBudget, setEditingBudget] = useState(false);

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

  const liveBudget = snap?.status?.budget_usd ?? snap?.controls?.budget_usd;
  useEffect(() => {
    if (!editingBudget && liveBudget != null) {
      setBudgetDraft(String(liveBudget));
    }
  }, [liveBudget, editingBudget]);

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

  const applyBudget = () => {
    const v = Number(budgetDraft);
    if (!Number.isFinite(v) || v < 10) {
      setError("Budget must be at least $10");
      return;
    }
    setEditingBudget(false);
    run(() => postControl("/api/controls/budget", { budget_usd: v }));
  };

  const status = snap?.status;
  const armed = Boolean(status?.armed);
  const liveClob = Boolean(status?.live_clob);
  const cities = snap?.cities ?? [];
  const positions = snap?.positions ?? [];
  const fills = snap?.fills ?? [];
  const skips = snap?.skips ?? [];
  const settlements = snap?.settlements ?? [];
  const visibleFills = liveClob
    ? fills.filter((f) => f.mode === "live")
    : fills;
  const liveSettlements = settlements.filter((s) => s.mode === "live");
  const paperSettlements = settlements.filter((s) => s.mode !== "live");
  const modeSettlements = liveClob ? liveSettlements : paperSettlements;
  const wins =
    modeSettlements.length > 0
      ? modeSettlements.filter((s) => s.result === "win").length
      : (status?.wins ?? 0);
  const losses =
    modeSettlements.length > 0
      ? modeSettlements.filter((s) => s.result === "loss").length
      : (status?.losses ?? 0);
  const budget = status?.budget_usd ?? snap?.controls?.budget_usd;
  const gains = status?.gains_usd ?? status?.pnl_today ?? 0;
  const openNotional = status?.open_notional ?? 0;
  const deployable = status?.deployable_usd ?? 0;
  const deployFrac = status?.max_deploy_frac ?? 0.75;
  const hitRate =
    wins + losses > 0 ? ((wins / (wins + losses)) * 100).toFixed(0) : null;

  return (
    <main className="mx-auto flex min-h-dvh max-w-lg flex-col gap-5 px-4 pb-14 pt-6">
      <header className="anim-rise">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-[1.65rem] font-semibold leading-none tracking-tight text-[var(--accent)]">
              WeatherBuyEnd
            </h1>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Late-day METAR BUY NO · ops
            </p>
          </div>
          <div className="text-right text-[11px] text-[var(--muted)]">
            <div
              className={`font-semibold ${armed ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
            >
              {armed ? "ARMED" : "FLAT"}
            </div>
            <div className="mono mt-0.5 uppercase tracking-wide">
              {status?.mode ?? "…"}
              {status?.live_clob ? " · CLOB" : status?.mock_markets ? " · mock" : ""}
            </div>
          </div>
        </div>

        {/* Wallet (live CLOB) vs stake budget (paper cap) */}
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-3.5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
              {status?.live_clob ? "Wallet" : "Budget"}
            </div>
            <div className="mono mt-1 text-[1.85rem] font-semibold leading-none tracking-tight text-[var(--ink)]">
              {usd(status?.live_clob ? (status?.wallet_usd ?? null) : budget)}
            </div>
            <div className="mono mt-2 text-[11px] text-[var(--muted)]">
              {status?.live_clob
                ? `CLOB USDC · cap ${usd(budget)}`
                : `deploy ≤${Math.round(deployFrac * 100)}% · free ${usd(deployable)}`}
            </div>
          </div>
          <div className="rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-3.5">
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">
              Gains
            </div>
            <div
              className={`mono mt-1 text-[1.85rem] font-semibold leading-none tracking-tight ${gains >= 0 ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
            >
              {money(gains)}
            </div>
            <div className="mono mt-2 text-[11px] text-[var(--muted)]">
              open {usd(openNotional)} · equity {usd(status?.equity_usd)}
            </div>
          </div>
        </div>
      </header>

      {status?.live_clob && status.wallet_usd == null ? (
        <div className="anim-rise rounded-2xl border border-[var(--warn)]/25 bg-[var(--warn-soft)] px-3.5 py-2.5 text-sm text-[var(--warn)]">
          Live CLOB on, but wallet USDC not loaded
          {status.wallet_error ? ` (${status.wallet_error})` : ""}. Stake cap is still
          the paper budget {usd(budget)}.
        </div>
      ) : null}
      {status?.live_clob && status.wallet_usd === 0 ? (
        <div className="anim-rise rounded-2xl border border-[var(--warn)]/25 bg-[var(--warn-soft)] px-3.5 py-2.5 text-sm text-[var(--warn)]">
          CLOB wallet is $0 (sig type {status.poly_sig_type ?? 0}
          {status.poly_funder_set ? ", funder set" : ", no POLY_FUNDER"}). If
          Polymarket.com shows cash, you are likely on a proxy/Magic wallet — set
          POLY_SIGNATURE_TYPE and POLY_FUNDER.
        </div>
      ) : null}
      {status?.live_clob && (status.fills_paper ?? 0) > 0 && (status.fills_live ?? 0) === 0 ? (
        <div className="anim-rise rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] px-3.5 py-2.5 text-sm text-[var(--muted)]">
          Ledger still has {status.fills_paper} paper fills — no live CLOB orders
          yet (attempts {status.live_order_attempts ?? 0}).
        </div>
      ) : null}
      {error && (
        <div className="anim-rise rounded-2xl border border-[var(--danger)]/25 bg-[var(--danger-soft)] px-3.5 py-2.5 text-sm text-[var(--danger)]">
          {error}
          <div className="mono mt-1 text-[11px] opacity-75">{API_URL || "/"}</div>
        </div>
      )}

      <section
        className={`anim-rise rounded-2xl border border-[var(--line)] bg-[var(--bg-elev)] p-4 ${armed ? "armed-glow" : ""}`}
      >
        <div className="grid grid-cols-4 gap-2">
          {[
            ["Open", status?.open_no_count ?? positions.length ?? "—"],
            ["W/L", `${wins}/${losses}`],
            ["Hit", hitRate != null ? `${hitRate}%` : "—"],
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
        <div className="mt-3 flex flex-col gap-2">
          {positions.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-3 text-center text-xs text-[var(--muted)]">
              No open trades
            </div>
          ) : (
            positions.map((p) => {
              const href = polymarketUrl({
                city: p.city,
                kind: p.kind,
                end_date: p.end_date,
                url: p.polymarket_url,
              });
              const title = (p.question || p.city || p.location_id || "").replace(
                /_/g,
                " ",
              );
              return (
                <div
                  key={p.market_id}
                  className="rounded-xl bg-[var(--bg)]/80 px-3 py-2.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold capitalize tracking-tight">
                        {(p.city || p.location_id || "").replace(/_/g, " ")}
                      </div>
                      <div className="mt-0.5 truncate text-[11px] text-[var(--muted)]">
                        {title}
                      </div>
                      <div className="mt-1">
                        <MarketLink href={href} />
                      </div>
                    </div>
                    <div className="shrink-0 text-right">
                      <div
                        className={`mono text-sm font-medium ${(p.unrealized_pnl ?? 0) >= 0 ? "text-[var(--ok)]" : "text-[var(--danger)]"}`}
                      >
                        {money(p.unrealized_pnl)}
                      </div>
                      <div className="mono mt-0.5 text-[11px] text-[var(--muted)]">
                        {p.entry_price.toFixed(3)} · ${p.size_usd.toFixed(2)}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
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

        <label className="mb-3 block">
          <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[var(--muted)]">
            Set budget
          </span>
          <div className="mt-1.5 flex gap-2">
            <input
              id="budget-input"
              type="number"
              min={10}
              step={10}
              inputMode="decimal"
              value={budgetDraft}
              onFocus={() => setEditingBudget(true)}
              onBlur={() => setEditingBudget(false)}
              onChange={(e) => setBudgetDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") applyBudget();
              }}
              className="mono min-h-12 flex-1 rounded-xl border border-[var(--line)] bg-[var(--bg)] px-3 text-base font-medium outline-none focus:border-[var(--accent)]"
              placeholder="500"
            />
            <button
              type="button"
              disabled={pending}
              onClick={applyBudget}
              className="tap min-h-12 shrink-0 rounded-xl bg-[var(--accent)] px-4 text-sm font-semibold text-white"
            >
              Save
            </button>
          </div>
          <span className="mt-1.5 block text-[11px] text-[var(--muted)]">
            Stake cap (not live wallet). Tickets scale with min(cap, wallet) · max{" "}
            {Math.round(deployFrac * 100)}% open at once
          </span>
        </label>

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
            ["fills", "Fills", visibleFills.length],
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
          {visibleFills.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[var(--line)] px-3 py-6 text-center text-sm text-[var(--muted)]">
              No fills yet
            </div>
          ) : (
            visibleFills.slice(0, 50).map((f) => {
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
