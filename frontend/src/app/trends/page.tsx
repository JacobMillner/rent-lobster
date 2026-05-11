"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import DetailModal from "@/components/DetailModal";
import { SourceBadge, Thumbnail, formatPrice } from "@/components/listingShared";
import { SALE_CONFIG } from "@/configs";
import { s } from "@/styles";
import type {
  PriceDrop,
  TrendNeighborhood,
  TrendPricePoint,
  TrendSummary,
  TrendVolumePoint,
} from "@/types";

function StatCard({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div style={s.statCard}>
      <div style={s.statValue}>{value}</div>
      <div style={s.statLabel}>{label}</div>
      {hint && <div style={trendStyles.statHint}>{hint}</div>}
    </div>
  );
}

function NeighborhoodTable({ rows }: { rows: TrendNeighborhood[] }) {
  const maxMedian = useMemo(() => {
    const vals = rows.map((r) => r.median_price ?? 0);
    return vals.length ? Math.max(...vals) : 0;
  }, [rows]);

  if (rows.length === 0) {
    return <p style={trendStyles.empty}>No neighborhoods yet.</p>;
  }

  return (
    <div style={trendStyles.tableWrap}>
      <table style={trendStyles.table}>
        <thead>
          <tr>
            <th style={trendStyles.th}>Neighborhood</th>
            <th style={{ ...trendStyles.th, textAlign: "right" }}>Listings</th>
            <th style={trendStyles.th}>Median Price</th>
            <th style={{ ...trendStyles.th, textAlign: "right" }}>$/sqft</th>
            <th style={{ ...trendStyles.th, textAlign: "right" }}>Range</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const pct = maxMedian > 0 && r.median_price ? (r.median_price / maxMedian) * 100 : 0;
            return (
              <tr key={r.neighborhood}>
                <td style={trendStyles.td}>{r.neighborhood}</td>
                <td style={{ ...trendStyles.td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {r.count}
                </td>
                <td style={trendStyles.td}>
                  <div style={trendStyles.barWrap}>
                    <div style={{ ...trendStyles.barFill, width: `${pct}%` }} />
                    <span style={trendStyles.barLabel}>{formatPrice(r.median_price)}</span>
                  </div>
                </td>
                <td style={{ ...trendStyles.td, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {r.median_price_per_sqft
                    ? `$${Math.round(r.median_price_per_sqft).toLocaleString()}`
                    : "\u2014"}
                </td>
                <td style={{ ...trendStyles.td, textAlign: "right", fontSize: 12, color: "#6b7280" }}>
                  {r.min_price && r.max_price
                    ? `${formatPrice(r.min_price)} \u2013 ${formatPrice(r.max_price)}`
                    : "\u2014"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type LineSeries = {
  label: string;
  color: string;
  points: { x: string; y: number | null }[];
};

function LineChart({
  series,
  height = 220,
  yFormat,
}: {
  series: LineSeries[];
  height?: number;
  yFormat?: (v: number) => string;
}) {
  const padding = { top: 12, right: 12, bottom: 30, left: 56 };
  const width = 720;

  const xs = useMemo(() => {
    const set = new Set<string>();
    for (const s of series) for (const p of s.points) set.add(p.x);
    return [...set].sort();
  }, [series]);

  const allValues = useMemo(() => {
    const out: number[] = [];
    for (const s of series) for (const p of s.points) if (p.y != null) out.push(p.y);
    return out;
  }, [series]);

  if (xs.length === 0 || allValues.length === 0) {
    return <div style={trendStyles.empty}>Not enough data yet.</div>;
  }

  const yMin = 0;
  const yMax = Math.max(...allValues) * 1.05 || 1;
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const xToPx = (i: number) =>
    padding.left + (xs.length <= 1 ? innerW / 2 : (i / (xs.length - 1)) * innerW);
  const yToPx = (v: number) =>
    padding.top + innerH - ((v - yMin) / (yMax - yMin)) * innerH;

  const gridLines = 4;
  const gridYs = Array.from({ length: gridLines + 1 }, (_, i) => yMin + ((yMax - yMin) * i) / gridLines);

  const fmt = yFormat ?? ((v: number) => v.toLocaleString());

  // Aim for at most ~6 x-axis labels.
  const labelEvery = Math.max(1, Math.ceil(xs.length / 6));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: "100%", height, display: "block" }}
      preserveAspectRatio="xMidYMid meet"
    >
      {gridYs.map((gy, i) => (
        <g key={i}>
          <line
            x1={padding.left}
            x2={padding.left + innerW}
            y1={yToPx(gy)}
            y2={yToPx(gy)}
            stroke="#e5e7eb"
            strokeDasharray="2 3"
          />
          <text
            x={padding.left - 6}
            y={yToPx(gy) + 4}
            fontSize={11}
            textAnchor="end"
            fill="#6b7280"
          >
            {fmt(gy)}
          </text>
        </g>
      ))}

      {xs.map((x, i) =>
        i % labelEvery === 0 || i === xs.length - 1 ? (
          <text
            key={x}
            x={xToPx(i)}
            y={padding.top + innerH + 18}
            fontSize={11}
            textAnchor="middle"
            fill="#6b7280"
          >
            {x}
          </text>
        ) : null,
      )}

      {series.map((line) => {
        const pts = line.points
          .map((p) => {
            const idx = xs.indexOf(p.x);
            if (idx < 0 || p.y == null) return null;
            return [xToPx(idx), yToPx(p.y)] as [number, number];
          })
          .filter((p): p is [number, number] => p !== null);
        if (pts.length === 0) return null;
        const d = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ");
        return (
          <g key={line.label}>
            <path d={d} fill="none" stroke={line.color} strokeWidth={2} />
            {pts.map((p, i) => (
              <circle key={i} cx={p[0]} cy={p[1]} r={3} fill={line.color} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

function PriceDropRow({
  drop,
  onClick,
}: {
  drop: PriceDrop;
  onClick: () => void;
}) {
  const diff = drop.prev_price - drop.latest_price;
  const pct = drop.prev_price > 0 ? (diff / drop.prev_price) * 100 : 0;
  return (
    <div style={trendStyles.dropCard} onClick={onClick}>
      <div style={trendStyles.dropThumb}>
        <Thumbnail thumbnailPath={drop.thumbnail_path} height={80} />
      </div>
      <div style={trendStyles.dropBody}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <SourceBadge source={drop.source} />
          {drop.neighborhood && (
            <span style={{ fontSize: 12, color: "#6b7280" }}>{drop.neighborhood}</span>
          )}
        </div>
        {drop.address && <p style={trendStyles.dropAddress}>{drop.address}</p>}
        <div style={trendStyles.dropMeta}>
          {drop.beds != null && <span>{drop.beds} bed</span>}
          {drop.baths != null && <span>{drop.baths} bath</span>}
        </div>
      </div>
      <div style={trendStyles.dropPrices}>
        <span style={trendStyles.dropOld}>{formatPrice(drop.prev_price)}</span>
        <span style={trendStyles.dropArrow}>&rarr;</span>
        <span style={trendStyles.dropNew}>{formatPrice(drop.latest_price)}</span>
        <span style={trendStyles.dropDelta}>
          &minus;{formatPrice(diff)} ({pct.toFixed(1)}%)
        </span>
      </div>
    </div>
  );
}

export default function TrendsPage() {
  const [summary, setSummary] = useState<TrendSummary | null>(null);
  const [neighborhoods, setNeighborhoods] = useState<TrendNeighborhood[]>([]);
  const [priceHistory, setPriceHistory] = useState<TrendPricePoint[]>([]);
  const [volume, setVolume] = useState<TrendVolumePoint[]>([]);
  const [drops, setDrops] = useState<PriceDrop[]>([]);
  const [selectedNeighborhood, setSelectedNeighborhood] = useState<string>("");
  const [modalListingId, setModalListingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    try {
      const qs = selectedNeighborhood
        ? `&neighborhood=${encodeURIComponent(selectedNeighborhood)}`
        : "";
      const [sumRes, nbRes, phRes, volRes, dropRes] = await Promise.all([
        fetch("/api/trends/summary?listing_type=sale"),
        fetch("/api/trends/neighborhoods?listing_type=sale"),
        fetch(`/api/trends/price-history?listing_type=sale&weeks=12${qs}`),
        fetch("/api/trends/listing-volume?listing_type=sale&weeks=12"),
        fetch("/api/trends/price-drops?listing_type=sale&limit=20"),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (nbRes.ok) setNeighborhoods(await nbRes.json());
      if (phRes.ok) setPriceHistory(await phRes.json());
      if (volRes.ok) setVolume(await volRes.json());
      if (dropRes.ok) setDrops(await dropRes.json());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trends");
    } finally {
      setLoading(false);
    }
  }, [selectedNeighborhood]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const priceHistorySeries: LineSeries[] = useMemo(() => {
    return [
      {
        label: "Avg price",
        color: "#dc2626",
        points: priceHistory.map((p) => ({ x: p.week, y: p.avg_price })),
      },
    ];
  }, [priceHistory]);

  const volumeSeries: LineSeries[] = useMemo(() => {
    return [
      {
        label: "New",
        color: "#22c55e",
        points: volume.map((p) => ({ x: p.week, y: p.new_count })),
      },
      {
        label: "Active",
        color: "#0369a1",
        points: volume.map((p) => ({ x: p.week, y: p.active_count })),
      },
    ];
  }, [volume]);

  const moneyFmt = (v: number) => `$${Math.round(v).toLocaleString()}`;
  const intFmt = (v: number) => Math.round(v).toLocaleString();

  return (
    <div style={s.page}>
      <header style={s.header}>
        <div style={s.headerInner}>
          <img src="/logo.png" alt="Rent Lobster" style={s.headerLogo} />
          <h1 style={s.title}>Buy Trends</h1>
          <p style={s.subtitle}>Pricing statistics and historical trends for sale listings</p>
        </div>
      </header>

      <main style={s.main}>
        {error && <p style={s.errorMsg}>{error}</p>}
        {loading && !summary && <p style={s.loadingMsg}>Loading trends...</p>}

        {summary && (
          <section style={s.statsRow}>
            <StatCard label="Active Sale Listings" value={summary.total.toLocaleString()} />
            <StatCard
              label="Median Price"
              value={summary.median_price ? formatPrice(Math.round(summary.median_price)) : "\u2014"}
              hint={summary.avg_price ? `avg ${formatPrice(Math.round(summary.avg_price))}` : undefined}
            />
            <StatCard
              label="Median $/sqft"
              value={
                summary.median_price_per_sqft
                  ? `$${Math.round(summary.median_price_per_sqft).toLocaleString()}`
                  : "\u2014"
              }
              hint={
                summary.avg_price_per_sqft
                  ? `avg $${Math.round(summary.avg_price_per_sqft).toLocaleString()}`
                  : undefined
              }
            />
            <StatCard
              label="Avg HOA / Mo"
              value={summary.avg_hoa ? `$${Math.round(summary.avg_hoa).toLocaleString()}` : "\u2014"}
            />
            <StatCard
              label="Avg Annual Tax"
              value={summary.avg_tax ? `$${Math.round(summary.avg_tax).toLocaleString()}` : "\u2014"}
            />
          </section>
        )}

        <section style={trendStyles.panel}>
          <h2 style={s.sectionTitle}>By Neighborhood</h2>
          <NeighborhoodTable rows={neighborhoods} />
        </section>

        <section style={trendStyles.panel}>
          <div style={trendStyles.panelHeader}>
            <h2 style={s.sectionTitle}>Price History (Last 12 Weeks)</h2>
            <select
              style={{ ...s.select, minWidth: 180 }}
              value={selectedNeighborhood}
              onChange={(e) => setSelectedNeighborhood(e.target.value)}
            >
              <option value="">All neighborhoods</option>
              {neighborhoods.map((n) => (
                <option key={n.neighborhood} value={n.neighborhood}>
                  {n.neighborhood}
                </option>
              ))}
            </select>
          </div>
          <LineChart series={priceHistorySeries} yFormat={moneyFmt} />
        </section>

        <section style={trendStyles.panel}>
          <h2 style={s.sectionTitle}>Listing Volume (Last 12 Weeks)</h2>
          <div style={trendStyles.legend}>
            <span style={trendStyles.legendItem}>
              <span style={{ ...trendStyles.legendDot, background: "#22c55e" }} />
              New listings per week
            </span>
            <span style={trendStyles.legendItem}>
              <span style={{ ...trendStyles.legendDot, background: "#0369a1" }} />
              Listings seen that week
            </span>
          </div>
          <LineChart series={volumeSeries} yFormat={intFmt} />
        </section>

        <section style={trendStyles.panel}>
          <h2 style={s.sectionTitle}>Recent Price Drops</h2>
          {drops.length === 0 ? (
            <p style={trendStyles.empty}>
              No price drops detected yet. The price-history table fills in as crawls re-encounter
              listings whose prices have changed.
            </p>
          ) : (
            <div style={trendStyles.dropList}>
              {drops.map((d) => (
                <PriceDropRow
                  key={d.id}
                  drop={d}
                  onClick={() => setModalListingId(d.id)}
                />
              ))}
            </div>
          )}
        </section>

        {summary && summary.beds_breakdown.length > 0 && (
          <section style={trendStyles.panel}>
            <h2 style={s.sectionTitle}>Beds Breakdown</h2>
            <div style={trendStyles.chipRow}>
              {summary.beds_breakdown.map((b) => (
                <span key={String(b.beds)} style={trendStyles.bigChip}>
                  <strong>{b.beds == null ? "?" : b.beds}</strong> bed
                  <span style={trendStyles.chipCount}>{b.count}</span>
                </span>
              ))}
            </div>
          </section>
        )}

        {summary && summary.property_type_breakdown.length > 0 && (
          <section style={trendStyles.panel}>
            <h2 style={s.sectionTitle}>Property Types</h2>
            <div style={trendStyles.chipRow}>
              {summary.property_type_breakdown.map((p) => (
                <span key={p.property_type} style={trendStyles.bigChip}>
                  {p.property_type}
                  <span style={trendStyles.chipCount}>{p.count}</span>
                </span>
              ))}
            </div>
          </section>
        )}
      </main>

      {modalListingId !== null && (
        <DetailModal
          listingId={modalListingId}
          onClose={() => setModalListingId(null)}
          onUpdate={fetchAll}
          config={SALE_CONFIG}
        />
      )}
    </div>
  );
}

const trendStyles: Record<string, React.CSSProperties> = {
  statHint: {
    fontSize: 11,
    color: "#9ca3af",
    marginTop: 2,
  },
  panel: {
    backgroundColor: "white",
    borderRadius: 12,
    padding: "20px 24px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
    marginBottom: 16,
  },
  panelHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 12,
    marginBottom: 12,
  },
  tableWrap: {
    overflowX: "auto",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 14,
  },
  th: {
    textAlign: "left",
    padding: "8px 12px",
    borderBottom: "1px solid #e5e7eb",
    color: "#6b7280",
    fontSize: 12,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  },
  td: {
    padding: "10px 12px",
    borderBottom: "1px solid #f3f4f6",
    color: "#111827",
    verticalAlign: "middle",
  },
  barWrap: {
    position: "relative",
    height: 22,
    minWidth: 120,
    backgroundColor: "#f3f4f6",
    borderRadius: 4,
    overflow: "hidden",
  },
  barFill: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    backgroundColor: "#fecaca",
  },
  barLabel: {
    position: "relative",
    padding: "0 8px",
    fontSize: 13,
    fontWeight: 600,
    color: "#111827",
    lineHeight: "22px",
  },
  empty: {
    color: "#6b7280",
    fontSize: 14,
    padding: "12px 0",
  },
  legend: {
    display: "flex",
    gap: 16,
    flexWrap: "wrap",
    marginBottom: 8,
  },
  legendItem: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    fontSize: 13,
    color: "#374151",
  },
  legendDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    display: "inline-block",
  },
  dropList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  dropCard: {
    display: "grid",
    gridTemplateColumns: "110px 1fr auto",
    gap: 14,
    alignItems: "center",
    padding: 10,
    borderRadius: 10,
    border: "1px solid #f3f4f6",
    cursor: "pointer",
    backgroundColor: "white",
    transition: "border-color 0.15s",
  },
  dropThumb: {
    width: 110,
    height: 80,
    overflow: "hidden",
    borderRadius: 8,
    backgroundColor: "#f1f5f9",
  },
  dropBody: {
    minWidth: 0,
  },
  dropAddress: {
    margin: "4px 0 2px",
    fontSize: 14,
    fontWeight: 500,
    color: "#111827",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  dropMeta: {
    display: "flex",
    gap: 8,
    fontSize: 12,
    color: "#6b7280",
  },
  dropPrices: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: 2,
    minWidth: 160,
    fontVariantNumeric: "tabular-nums",
  },
  dropOld: {
    fontSize: 13,
    color: "#9ca3af",
    textDecoration: "line-through",
  },
  dropArrow: {
    fontSize: 12,
    color: "#9ca3af",
  },
  dropNew: {
    fontSize: 16,
    fontWeight: 700,
    color: "#16a34a",
  },
  dropDelta: {
    fontSize: 12,
    color: "#16a34a",
    fontWeight: 600,
  },
  chipRow: {
    display: "flex",
    gap: 10,
    flexWrap: "wrap",
  },
  bigChip: {
    display: "inline-flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 14px",
    borderRadius: 10,
    backgroundColor: "#f3f4f6",
    fontSize: 14,
    color: "#374151",
    fontWeight: 500,
    textTransform: "capitalize",
  },
  chipCount: {
    fontSize: 13,
    fontWeight: 700,
    color: "#111827",
    backgroundColor: "white",
    padding: "2px 8px",
    borderRadius: 999,
  },
};
