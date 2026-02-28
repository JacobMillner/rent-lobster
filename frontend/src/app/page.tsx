"use client";

import { useEffect, useState, useCallback, useRef } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Listing {
  id: number;
  source: string;
  url: string;
  price: number | null;
  beds: number | null;
  baths: number | null;
  address: string | null;
  neighborhood: string | null;
  thumbnail_path: string | null;
  created_at: string;
}

interface Stats {
  total: number;
  sources: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
}

interface CrawlStatus {
  id?: string;
  status: string;
  spiders?: string[];
  max_pages?: number;
  pages_crawled?: number;
  listings_found?: number;
  current_spider?: string | null;
  error?: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALL_SPIDERS = ["craigslist", "streeteasy", "zillow"] as const;

const SOURCE_COLORS: Record<string, string> = {
  craigslist: "#6b21a8",
  streeteasy: "#0369a1",
  zillow: "#0e7490",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(price: number | null): string {
  if (price === null) return "\u2014";
  return `$${price.toLocaleString()}`;
}

// ---------------------------------------------------------------------------
// Small components
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={s.statCard}>
      <div style={s.statValue}>{value}</div>
      <div style={s.statLabel}>{label}</div>
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  const bg = SOURCE_COLORS[source] ?? "#374151";
  return <span style={{ ...s.badge, backgroundColor: bg }}>{source}</span>;
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label style={s.checkboxLabel}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={s.checkbox}
      />
      {label}
    </label>
  );
}

function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div style={s.progressWrap}>
      <div style={s.progressTrack}>
        <div
          style={{
            ...s.progressFill,
            width: `${Math.min(pct, 100)}%`,
          }}
        />
      </div>
      <div style={s.progressLabel}>{label}</div>
    </div>
  );
}

function Thumbnail({ listing }: { listing: Listing }) {
  const [err, setErr] = useState(false);
  if (!listing.thumbnail_path || err) {
    return (
      <div style={s.thumbPlaceholder}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" strokeWidth="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="m21 15-5-5L5 21" />
        </svg>
      </div>
    );
  }
  return (
    <img
      src={`/api/thumbnails/${listing.thumbnail_path}`}
      alt=""
      style={s.thumbImg}
      onError={() => setErr(true)}
    />
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Home() {
  // Data
  const [listings, setListings] = useState<Listing[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterSource, setFilterSource] = useState("");
  const [filterMaxPrice, setFilterMaxPrice] = useState("");
  const [filterMinBeds, setFilterMinBeds] = useState("");

  // Crawl controls
  const [selectedSpiders, setSelectedSpiders] = useState<Set<string>>(
    new Set(ALL_SPIDERS)
  );
  const [maxPages, setMaxPages] = useState("50");
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null);
  const [starting, setStarting] = useState(false);

  // Polling ref so we can clear on unmount
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thumbPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ------- Fetchers --------------------------------------------------------

  const fetchListings = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (filterSource) params.set("source", filterSource);
      if (filterMaxPrice) params.set("max_price", filterMaxPrice);
      if (filterMinBeds) params.set("min_beds", filterMinBeds);
      const qs = params.toString();
      const res = await fetch(`/api/listings${qs ? `?${qs}` : ""}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Listing[] = await res.json();
      setListings(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load listings");
    } finally {
      setLoading(false);
    }
  }, [filterSource, filterMaxPrice, filterMinBeds]);

  const fetchMeta = useCallback(async () => {
    try {
      const [srcRes, statRes] = await Promise.all([
        fetch("/api/sources"),
        fetch("/api/stats"),
      ]);
      if (srcRes.ok) setSources(await srcRes.json());
      if (statRes.ok) setStats(await statRes.json());
    } catch {
      /* non-critical */
    }
  }, []);

  const fetchCrawlStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/crawl/status");
      if (res.ok) setCrawlStatus(await res.json());
    } catch {
      /* ignore */
    }
  }, []);

  // ------- Initial load ----------------------------------------------------

  useEffect(() => {
    fetchListings();
    fetchMeta();
    fetchCrawlStatus();
  }, [fetchListings, fetchMeta, fetchCrawlStatus]);

  // ------- Polling while crawl is running ----------------------------------

  const isRunning = crawlStatus?.status === "running";
  const isActive =
    crawlStatus?.status === "running" || crawlStatus?.status === "pending";

  useEffect(() => {
    if (!isActive) {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    pollRef.current = setInterval(() => {
      fetchCrawlStatus();
      fetchListings();
      fetchMeta();
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [isActive, fetchCrawlStatus, fetchListings, fetchMeta]);

  // Slower poll for thumbnails that keeps going briefly after crawl ends
  useEffect(() => {
    thumbPollRef.current = setInterval(() => {
      fetchListings();
    }, 8000);
    return () => {
      if (thumbPollRef.current) clearInterval(thumbPollRef.current);
    };
  }, [fetchListings]);

  // ------- Handlers --------------------------------------------------------

  const toggleSpider = (name: string, on: boolean) => {
    setSelectedSpiders((prev) => {
      const next = new Set(prev);
      on ? next.add(name) : next.delete(name);
      return next;
    });
  };

  const startCrawl = async () => {
    if (selectedSpiders.size === 0) return;
    setStarting(true);
    try {
      const res = await fetch("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spiders: [...selectedSpiders],
          max_pages: parseInt(maxPages) || 50,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setCrawlStatus(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start crawl");
    } finally {
      setStarting(false);
    }
  };

  // ------- Progress computation -------------------------------------------

  const totalMax =
    (crawlStatus?.max_pages ?? 50) * (crawlStatus?.spiders?.length ?? 1);
  const pct =
    totalMax > 0 ? ((crawlStatus?.pages_crawled ?? 0) / totalMax) * 100 : 0;

  // ------- Render ----------------------------------------------------------

  return (
    <div style={s.page}>
      {/* Header */}
      <header style={s.header}>
        <div style={s.headerInner}>
          <h1 style={s.title}>Rent Lobster</h1>
          <p style={s.subtitle}>Apartment Listing Aggregator</p>
        </div>
      </header>

      <main style={s.main}>
        {/* ---- Crawl Control Panel ---- */}
        <section style={s.crawlPanel}>
          <h2 style={s.sectionTitle}>Start a Crawl</h2>

          <div style={s.crawlControls}>
            <div style={s.spiderChecks}>
              {ALL_SPIDERS.map((name) => (
                <Checkbox
                  key={name}
                  label={name.charAt(0).toUpperCase() + name.slice(1)}
                  checked={selectedSpiders.has(name)}
                  onChange={(v) => toggleSpider(name, v)}
                />
              ))}
            </div>

            <div style={s.crawlRight}>
              <label style={s.inlineLabel}>
                Max pages
                <input
                  type="number"
                  min={1}
                  max={500}
                  value={maxPages}
                  onChange={(e) => setMaxPages(e.target.value)}
                  style={{ ...s.input, width: 80 }}
                />
              </label>

              <button
                style={{
                  ...s.button,
                  opacity: isRunning || starting ? 0.6 : 1,
                  cursor: isRunning || starting ? "not-allowed" : "pointer",
                }}
                disabled={isRunning || starting || selectedSpiders.size === 0}
                onClick={startCrawl}
              >
                {isRunning ? "Crawling\u2026" : starting ? "Starting\u2026" : "Start Crawl"}
              </button>
            </div>
          </div>

          {/* Progress */}
          {crawlStatus && crawlStatus.status !== "idle" && (
            <div style={{ marginTop: 16 }}>
              {isActive && (
                <ProgressBar
                  pct={pct}
                  label={
                    crawlStatus.status === "pending"
                      ? "Starting crawl\u2026"
                      : `${crawlStatus.current_spider ?? ""} \u2014 ${crawlStatus.pages_crawled} pages \u00b7 ${crawlStatus.listings_found} listings`
                  }
                />
              )}

              {crawlStatus.status === "completed" && (
                <div style={s.crawlDone}>
                  Crawl completed &mdash; {crawlStatus.pages_crawled} pages
                  processed, {crawlStatus.listings_found} listings found.
                </div>
              )}

              {crawlStatus.status === "error" && (
                <div style={s.crawlError}>
                  Crawl failed: {crawlStatus.error}
                </div>
              )}
            </div>
          )}
        </section>

        {/* ---- Stats ---- */}
        {stats && stats.total > 0 && (
          <section style={s.statsRow}>
            <StatCard label="Total Listings" value={String(stats.total)} />
            <StatCard label="Sources" value={String(stats.sources)} />
            <StatCard
              label="Avg Price"
              value={
                stats.avg_price
                  ? formatPrice(Math.round(stats.avg_price))
                  : "\u2014"
              }
            />
            <StatCard
              label="Price Range"
              value={
                stats.min_price && stats.max_price
                  ? `${formatPrice(stats.min_price)} \u2013 ${formatPrice(stats.max_price)}`
                  : "\u2014"
              }
            />
          </section>
        )}

        {/* ---- Filters ---- */}
        <section style={s.filters}>
          <select
            style={s.select}
            value={filterSource}
            onChange={(e) => setFilterSource(e.target.value)}
          >
            <option value="">All Sources</option>
            {sources.map((src) => (
              <option key={src} value={src}>
                {src}
              </option>
            ))}
          </select>

          <input
            style={s.input}
            type="number"
            placeholder="Max price"
            value={filterMaxPrice}
            onChange={(e) => setFilterMaxPrice(e.target.value)}
          />

          <input
            style={s.input}
            type="number"
            placeholder="Min beds"
            value={filterMinBeds}
            onChange={(e) => setFilterMinBeds(e.target.value)}
          />

          <button style={s.button} onClick={fetchListings}>
            Apply
          </button>
        </section>

        {/* ---- Error ---- */}
        {error && <p style={s.errorMsg}>{error}</p>}

        {/* ---- Results ---- */}
        {loading ? (
          <p style={s.loadingMsg}>Loading listings...</p>
        ) : listings.length === 0 ? (
          <div style={s.empty}>
            <p style={{ fontSize: 18, color: "#6b7280" }}>
              No listings found. Start a crawl above or run{" "}
              <code>make run</code> from the terminal.
            </p>
          </div>
        ) : (
          <div style={s.grid}>
            {listings.map((listing) => (
              <a
                key={listing.id}
                href={listing.url}
                target="_blank"
                rel="noopener noreferrer"
                style={s.card}
                onMouseEnter={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.transform = "translateY(-2px)";
                  el.style.boxShadow = "0 8px 25px rgba(0,0,0,0.12)";
                }}
                onMouseLeave={(e) => {
                  const el = e.currentTarget as HTMLElement;
                  el.style.transform = "none";
                  el.style.boxShadow = "0 1px 3px rgba(0,0,0,0.08)";
                }}
              >
                <Thumbnail listing={listing} />

                <div style={s.cardHeader}>
                  <SourceBadge source={listing.source} />
                  <span style={s.price}>{formatPrice(listing.price)}</span>
                </div>

                <div style={s.cardBody}>
                  {listing.address && (
                    <p style={s.address}>{listing.address}</p>
                  )}
                  {listing.neighborhood && (
                    <p style={s.neighborhood}>{listing.neighborhood}</p>
                  )}
                  <div style={s.details}>
                    {listing.beds !== null && (
                      <span style={s.detail}>{listing.beds} bed</span>
                    )}
                    {listing.baths !== null && (
                      <span style={s.detail}>{listing.baths} bath</span>
                    )}
                  </div>
                </div>

                <div style={s.cardFooter}>
                  <span>
                    {new Date(listing.created_at).toLocaleDateString()}
                  </span>
                  <span style={s.linkText}>View listing &rarr;</span>
                </div>
              </a>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const s: Record<string, React.CSSProperties> = {
  page: { minHeight: "100vh", backgroundColor: "#f8fafc" },

  /* Header */
  header: {
    background: "linear-gradient(135deg, #dc2626 0%, #991b1b 100%)",
    padding: "40px 20px",
    color: "white",
  },
  headerInner: { maxWidth: 1200, margin: "0 auto" },
  title: { margin: 0, fontSize: 36, fontWeight: 800, letterSpacing: "-0.02em" },
  subtitle: { margin: "8px 0 0", fontSize: 16, opacity: 0.85, fontWeight: 400 },

  main: { maxWidth: 1200, margin: "0 auto", padding: "24px 20px 60px" },

  /* Crawl panel */
  crawlPanel: {
    backgroundColor: "white",
    borderRadius: 12,
    padding: "24px 28px",
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
    marginBottom: 24,
  },
  sectionTitle: { margin: "0 0 16px", fontSize: 18, fontWeight: 700, color: "#111827" },
  crawlControls: {
    display: "flex",
    flexWrap: "wrap" as const,
    justifyContent: "space-between",
    alignItems: "center",
    gap: 16,
  },
  spiderChecks: { display: "flex", gap: 20, flexWrap: "wrap" as const },
  crawlRight: { display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" as const },
  checkboxLabel: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    fontSize: 15,
    fontWeight: 500,
    color: "#374151",
    cursor: "pointer",
    userSelect: "none" as const,
  },
  checkbox: { width: 18, height: 18, accentColor: "#dc2626", cursor: "pointer" },
  inlineLabel: { display: "flex", alignItems: "center", gap: 8, fontSize: 14, color: "#374151" },

  /* Progress */
  progressWrap: { marginTop: 4 },
  progressTrack: {
    height: 10,
    borderRadius: 5,
    backgroundColor: "#e5e7eb",
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 5,
    backgroundColor: "#dc2626",
    transition: "width 0.4s ease",
  },
  progressLabel: { marginTop: 6, fontSize: 13, color: "#6b7280" },
  crawlDone: {
    padding: "10px 14px",
    borderRadius: 8,
    backgroundColor: "#f0fdf4",
    color: "#166534",
    fontSize: 14,
    border: "1px solid #bbf7d0",
  },
  crawlError: {
    padding: "10px 14px",
    borderRadius: 8,
    backgroundColor: "#fef2f2",
    color: "#991b1b",
    fontSize: 14,
    border: "1px solid #fecaca",
  },

  /* Stats */
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
  statValue: { fontSize: 28, fontWeight: 700, color: "#111827" },
  statLabel: {
    fontSize: 13,
    color: "#6b7280",
    marginTop: 4,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
  },

  /* Filters */
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

  /* Messages */
  errorMsg: {
    color: "#dc2626",
    backgroundColor: "#fef2f2",
    padding: "12px 16px",
    borderRadius: 8,
    border: "1px solid #fecaca",
  },
  loadingMsg: { textAlign: "center" as const, color: "#6b7280", padding: 40, fontSize: 16 },
  empty: {
    textAlign: "center" as const,
    padding: "60px 20px",
    backgroundColor: "white",
    borderRadius: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
  },

  /* Grid & Cards */
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
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
  thumbImg: {
    width: "100%",
    height: 180,
    objectFit: "cover" as const,
    display: "block",
  },
  thumbPlaceholder: {
    width: "100%",
    height: 120,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#f1f5f9",
  },
  cardHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "14px 20px 0",
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
  price: { fontSize: 22, fontWeight: 700, color: "#111827" },
  cardBody: { padding: "10px 20px", flex: 1 },
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
  neighborhood: { margin: "0 0 8px", fontSize: 13, color: "#6b7280" },
  details: { display: "flex", gap: 12 },
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
  linkText: { color: "#dc2626", fontWeight: 500 },
};
