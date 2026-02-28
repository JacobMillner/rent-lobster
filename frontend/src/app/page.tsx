"use client";

import { useEffect, useState, useCallback } from "react";

interface Listing {
  id: number;
  source: string;
  url: string;
  price: number | null;
  beds: number | null;
  baths: number | null;
  address: string | null;
  neighborhood: string | null;
  created_at: string;
}

interface Stats {
  total: number;
  sources: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
}

const SOURCE_COLORS: Record<string, string> = {
  craigslist: "#6b21a8",
  streeteasy: "#0369a1",
  zillow: "#0e7490",
};

function formatPrice(price: number | null): string {
  if (price === null) return "—";
  return `$${price.toLocaleString()}`;
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={styles.statCard}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const bg = SOURCE_COLORS[source] ?? "#374151";
  return (
    <span
      style={{
        ...styles.badge,
        backgroundColor: bg,
      }}
    >
      {source}
    </span>
  );
}

export default function Home() {
  const [listings, setListings] = useState<Listing[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [filterSource, setFilterSource] = useState("");
  const [filterMaxPrice, setFilterMaxPrice] = useState("");
  const [filterMinBeds, setFilterMinBeds] = useState("");

  const fetchListings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filterSource) params.set("source", filterSource);
      if (filterMaxPrice) params.set("max_price", filterMaxPrice);
      if (filterMinBeds) params.set("min_beds", filterMinBeds);

      const qs = params.toString();
      const res = await fetch(`/api/listings${qs ? `?${qs}` : ""}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setListings(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load listings");
    } finally {
      setLoading(false);
    }
  }, [filterSource, filterMaxPrice, filterMinBeds]);

  useEffect(() => {
    fetchListings();
  }, [fetchListings]);

  useEffect(() => {
    fetch("/api/sources")
      .then((r) => r.json())
      .then(setSources)
      .catch(() => {});
    fetch("/api/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <div style={styles.headerInner}>
          <h1 style={styles.title}>Rent Lobster</h1>
          <p style={styles.subtitle}>Apartment Listing Aggregator</p>
        </div>
      </header>

      <main style={styles.main}>
        {stats && stats.total > 0 && (
          <section style={styles.statsRow}>
            <StatCard label="Total Listings" value={String(stats.total)} />
            <StatCard label="Sources" value={String(stats.sources)} />
            <StatCard
              label="Avg Price"
              value={stats.avg_price ? formatPrice(Math.round(stats.avg_price)) : "—"}
            />
            <StatCard label="Price Range" value={
              stats.min_price && stats.max_price
                ? `${formatPrice(stats.min_price)} – ${formatPrice(stats.max_price)}`
                : "—"
            } />
          </section>
        )}

        <section style={styles.filters}>
          <select
            style={styles.select}
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
          >
            <option value="">All Sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>

          <input
            style={styles.input}
            type="number"
            placeholder="Max price"
            value={filterMaxPrice}
            onChange={(e) => setFilterMaxPrice(e.target.value)}
          />

          <input
            style={styles.input}
            type="number"
            placeholder="Min beds"
            value={filterMinBeds}
            onChange={(e) => setFilterMinBeds(e.target.value)}
          />

          <button style={styles.button} onClick={fetchListings}>
            Apply
          </button>
        </section>

        {error && <p style={styles.error}>{error}</p>}

        {loading ? (
          <p style={styles.loading}>Loading listings...</p>
        ) : listings.length === 0 ? (
          <div style={styles.empty}>
            <p style={{ fontSize: 18, color: "#6b7280" }}>
              No listings found. Run the crawler first with <code>make run</code>.
            </p>
          </div>
        ) : (
          <div style={styles.grid}>
            {listings.map((listing) => (
              <a
                key={listing.id}
                href={listing.url}
                target="_blank"
                rel="noopener noreferrer"
                style={styles.card}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLElement).style.transform = "translateY(-2px)";
                  (e.currentTarget as HTMLElement).style.boxShadow = "0 8px 25px rgba(0,0,0,0.12)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLElement).style.transform = "none";
                  (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.08)";
                }}
              >
                <div style={styles.cardHeader}>
                  <SourceBadge source={listing.source} />
                  <span style={styles.price}>{formatPrice(listing.price)}</span>
                </div>

                <div style={styles.cardBody}>
                  {listing.address && (
                    <p style={styles.address}>{listing.address}</p>
                  )}
                  {listing.neighborhood && (
                    <p style={styles.neighborhood}>{listing.neighborhood}</p>
                  )}
                  <div style={styles.details}>
                    {listing.beds !== null && (
                      <span style={styles.detail}>{listing.beds} bed</span>
                    )}
                    {listing.baths !== null && (
                      <span style={styles.detail}>{listing.baths} bath</span>
                    )}
                  </div>
                </div>

                <div style={styles.cardFooter}>
                  <span style={styles.date}>
                    {new Date(listing.created_at).toLocaleDateString()}
                  </span>
                  <span style={styles.linkText}>View listing &rarr;</span>
                </div>
              </a>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    backgroundColor: "#f8fafc",
  },
  header: {
    background: "linear-gradient(135deg, #dc2626 0%, #991b1b 100%)",
    padding: "40px 20px",
    color: "white",
  },
  headerInner: {
    maxWidth: 1200,
    margin: "0 auto",
  },
  title: {
    margin: 0,
    fontSize: 36,
    fontWeight: 800,
    letterSpacing: "-0.02em",
  },
  subtitle: {
    margin: "8px 0 0",
    fontSize: 16,
    opacity: 0.85,
    fontWeight: 400,
  },
  main: {
    maxWidth: 1200,
    margin: "0 auto",
    padding: "24px 20px 60px",
  },
  statsRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
    gap: 16,
    marginBottom: 24,
  },
  statCard: {
    backgroundColor: "white",
    borderRadius: 12,
    padding: "20px 24px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
  },
  statValue: {
    fontSize: 28,
    fontWeight: 700,
    color: "#111827",
  },
  statLabel: {
    fontSize: 13,
    color: "#6b7280",
    marginTop: 4,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
  },
  filters: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: 12,
    marginBottom: 24,
    alignItems: "center",
  },
  select: {
    padding: "10px 14px",
    borderRadius: 8,
    border: "1px solid #d1d5db",
    fontSize: 14,
    backgroundColor: "white",
    minWidth: 150,
  },
  input: {
    padding: "10px 14px",
    borderRadius: 8,
    border: "1px solid #d1d5db",
    fontSize: 14,
    width: 130,
  },
  button: {
    padding: "10px 20px",
    borderRadius: 8,
    border: "none",
    backgroundColor: "#dc2626",
    color: "white",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
  },
  error: {
    color: "#dc2626",
    backgroundColor: "#fef2f2",
    padding: "12px 16px",
    borderRadius: 8,
    border: "1px solid #fecaca",
  },
  loading: {
    textAlign: "center" as const,
    color: "#6b7280",
    padding: 40,
    fontSize: 16,
  },
  empty: {
    textAlign: "center" as const,
    padding: "60px 20px",
    backgroundColor: "white",
    borderRadius: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
    gap: 16,
  },
  card: {
    display: "flex",
    flexDirection: "column" as const,
    backgroundColor: "white",
    borderRadius: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
    overflow: "hidden",
    textDecoration: "none",
    color: "inherit",
    transition: "transform 0.15s, box-shadow 0.15s",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "16px 20px 0",
  },
  badge: {
    display: "inline-block",
    padding: "4px 10px",
    borderRadius: 20,
    fontSize: 12,
    fontWeight: 600,
    color: "white",
    textTransform: "capitalize" as const,
  },
  price: {
    fontSize: 22,
    fontWeight: 700,
    color: "#111827",
  },
  cardBody: {
    padding: "12px 20px",
    flex: 1,
  },
  address: {
    margin: "0 0 4px",
    fontSize: 15,
    fontWeight: 500,
    color: "#1f2937",
    lineHeight: 1.4,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap" as const,
  },
  neighborhood: {
    margin: "0 0 8px",
    fontSize: 13,
    color: "#6b7280",
  },
  details: {
    display: "flex",
    gap: 12,
  },
  detail: {
    fontSize: 13,
    color: "#374151",
    backgroundColor: "#f3f4f6",
    padding: "3px 8px",
    borderRadius: 6,
  },
  cardFooter: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "12px 20px",
    borderTop: "1px solid #f3f4f6",
    fontSize: 13,
    color: "#9ca3af",
  },
  date: {},
  linkText: {
    color: "#dc2626",
    fontWeight: 500,
  },
};
