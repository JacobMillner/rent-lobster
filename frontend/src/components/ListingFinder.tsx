"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import dynamic from "next/dynamic";
import type {
  Listing,
  PaginatedResponse,
  Stats,
  CrawlStatus,
  MapListing,
  ListingFinderConfig,
  SavedSearch,
  LocationCatalog,
  Borough,
  Neighborhood,
} from "@/types";
import { s } from "@/styles";
import DetailModal from "./DetailModal";
import {
  SourceBadge,
  StarButton,
  StatusDot,
  Thumbnail,
  formatPrice,
  getStatus,
} from "./listingShared";

const ALL_SPIDERS = ["craigslist", "streeteasy", "zillow"] as const;
const PER_PAGE = 24;

function getAmenities(listing: Listing, labels: Record<string, string>): string[] {
  const result: string[] = [];
  for (const [key, label] of Object.entries(labels)) {
    if (listing[key as keyof Listing]) result.push(label);
  }
  if (listing.laundry === "in_unit") result.push("W/D In Unit");
  else if (listing.laundry === "in_building") result.push("W/D In Bldg");
  return result;
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={s.statCard}>
      <div style={s.statValue}>{value}</div>
      <div style={s.statLabel}>{label}</div>
    </div>
  );
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
        <div style={{ ...s.progressFill, width: `${Math.min(pct, 100)}%` }} />
      </div>
      <div style={s.progressLabel}>{label}</div>
    </div>
  );
}

function AmenityChips({ listing, labels }: { listing: Listing; labels: Record<string, string> }) {
  const amenities = getAmenities(listing, labels);
  if (amenities.length === 0) return null;
  return (
    <div style={s.chipRow}>
      {amenities.slice(0, 4).map((a) => (
        <span key={a} style={s.chip}>{a}</span>
      ))}
      {amenities.length > 4 && <span style={s.chip}>+{amenities.length - 4}</span>}
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (p: number) => void;
}) {
  if (totalPages <= 1) return null;

  const pages: (number | string)[] = [];
  const spread = 2;
  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= page - spread && i <= page + spread)) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== "...") {
      pages.push("...");
    }
  }

  return (
    <div style={s.pagination}>
      <button
        style={{ ...s.pageBtn, opacity: page <= 1 ? 0.4 : 1 }}
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        Previous
      </button>
      {pages.map((p, i) =>
        typeof p === "string" ? (
          <span key={`e${i}`} style={s.pageEllipsis}>{p}</span>
        ) : (
          <button
            key={p}
            style={{ ...s.pageBtn, ...(p === page ? s.pageBtnActive : {}) }}
            onClick={() => onPageChange(p)}
          >
            {p}
          </button>
        )
      )}
      <button
        style={{ ...s.pageBtn, opacity: page >= totalPages ? 0.4 : 1 }}
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Next
      </button>
    </div>
  );
}

function ListingsMapInner({
  markers,
  onMarkerClick,
  showNoFee,
}: {
  markers: MapListing[];
  onMarkerClick: (id: number) => void;
  showNoFee: boolean;
}) {
  const L = require("leaflet") as typeof import("leaflet");
  const { MapContainer, TileLayer, Marker, Popup, useMap } = require("react-leaflet");
  require("leaflet/dist/leaflet.css");

  const defaultIcon = useMemo(() => {
    return L.divIcon({
      className: "",
      html: `<div style="
        background:#dc2626;width:12px;height:12px;border-radius:50%;
        border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.4);
      "></div>`,
      iconSize: [12, 12],
      iconAnchor: [6, 6],
      popupAnchor: [0, -8],
    });
  }, [L]);

  function FitBounds({ markers: m }: { markers: MapListing[] }) {
    const map = useMap();
    useEffect(() => {
      if (m.length === 0) return;
      const bounds = L.latLngBounds(m.map((mk) => [mk.latitude, mk.longitude] as [number, number]));
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
    }, [m, map]);
    return null;
  }

  if (markers.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 60, color: "#6b7280" }}>
        No listings with map coordinates yet. Coordinates are resolved automatically in the background.
      </div>
    );
  }

  const center: [number, number] = [
    markers.reduce((sum, m) => sum + m.latitude, 0) / markers.length,
    markers.reduce((sum, m) => sum + m.longitude, 0) / markers.length,
  ];

  return (
    <MapContainer
      center={center}
      zoom={12}
      style={{ height: 600, width: "100%", borderRadius: 12, overflow: "hidden" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <FitBounds markers={markers} />
      {markers.map((m) => (
        <Marker key={m.id} position={[m.latitude, m.longitude]} icon={defaultIcon}>
          <Popup>
            <div style={{ minWidth: 180, fontSize: 13 }}>
              {m.thumbnail_path && (
                <img
                  src={`/api/thumbnails/${m.thumbnail_path}`}
                  alt=""
                  style={{ width: "100%", height: 80, objectFit: "cover", borderRadius: 4, marginBottom: 6 }}
                />
              )}
              <div style={{ fontWeight: 700, fontSize: 16, color: "#111827" }}>
                {m.price ? `$${m.price.toLocaleString()}` : "\u2014"}
                {showNoFee && m.no_fee ? <span style={{ fontSize: 10, color: "#16a34a", marginLeft: 6 }}>No Fee</span> : null}
              </div>
              {m.address && <div style={{ color: "#374151", marginTop: 2 }}>{m.address}</div>}
              {m.neighborhood && <div style={{ color: "#6b7280", fontSize: 12 }}>{m.neighborhood}</div>}
              <div style={{ color: "#6b7280", marginTop: 2 }}>
                {m.beds != null ? `${m.beds} bed` : ""}
                {m.baths != null ? ` \u00b7 ${m.baths} bath` : ""}
              </div>
              <button
                onClick={() => onMarkerClick(m.id)}
                style={{
                  marginTop: 6, padding: "4px 10px", borderRadius: 6, border: "1px solid #dc2626",
                  background: "white", color: "#dc2626", fontSize: 12, fontWeight: 600, cursor: "pointer",
                }}
              >
                View Details
              </button>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}

const ListingsMap = dynamic(
  () => Promise.resolve(ListingsMapInner),
  { ssr: false, loading: () => <div style={{ textAlign: "center", padding: 60, color: "#6b7280" }}>Loading map...</div> }
);

const savedStyles: Record<string, React.CSSProperties> = {
  savedBar: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
    marginBottom: 12,
  },
  savedLabel: {
    fontSize: 13,
    color: "#6b7280",
    marginRight: 4,
  },
  pill: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "5px 10px",
    borderRadius: 999,
    backgroundColor: "white",
    border: "1px solid #d1d5db",
    fontSize: 13,
    color: "#374151",
    cursor: "pointer",
    fontWeight: 500,
  },
  pillX: {
    background: "none",
    border: "none",
    color: "#9ca3af",
    fontSize: 16,
    cursor: "pointer",
    padding: 0,
    lineHeight: 1,
  },
  secondaryButton: {
    padding: "10px 16px",
    borderRadius: 8,
    border: "1px solid #d1d5db",
    backgroundColor: "white",
    fontSize: 14,
    fontWeight: 500,
    cursor: "pointer",
    color: "#374151",
  },
  linkButton: {
    background: "none",
    border: "none",
    color: "#6b7280",
    fontSize: 13,
    cursor: "pointer",
    padding: "8px 4px",
  },
  saveForm: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
};

function SavedSearchesBar({
  searches,
  onApply,
  onDelete,
}: {
  searches: SavedSearch[];
  onApply: (s: SavedSearch) => void;
  onDelete: (id: number) => void;
}) {
  if (searches.length === 0) return null;
  return (
    <div style={savedStyles.savedBar}>
      <span style={savedStyles.savedLabel}>Saved searches:</span>
      {searches.map((saved) => (
        <span key={saved.id} style={savedStyles.pill} onClick={() => onApply(saved)}>
          {saved.name}
          <button
            style={savedStyles.pillX}
            onClick={(e) => { e.stopPropagation(); onDelete(saved.id); }}
            title={`Delete "${saved.name}"`}
            aria-label={`Delete saved search ${saved.name}`}
          >
            &times;
          </button>
        </span>
      ))}
    </div>
  );
}

export default function ListingFinder({ config }: { config: ListingFinderConfig }) {
  const [listings, setListings] = useState<Listing[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE));

  const [filterSource, setFilterSource] = useState("");
  const [filterMaxPrice, setFilterMaxPrice] = useState("");
  const [filterMinBeds, setFilterMinBeds] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterFavorites, setFilterFavorites] = useState(false);
  const [sortBy, setSortBy] = useState("date_listed");

  const [selectedSpiders, setSelectedSpiders] = useState<Set<string>>(new Set(ALL_SPIDERS));
  const [maxPages, setMaxPages] = useState("50");
  const [crawlStatus, setCrawlStatus] = useState<CrawlStatus | null>(null);
  const [starting, setStarting] = useState(false);

  const [locationCatalog, setLocationCatalog] = useState<LocationCatalog>({ boroughs: [], neighborhoods: [] });
  const [crawlBorough, setCrawlBorough] = useState("brooklyn");
  const [crawlNeighborhood, setCrawlNeighborhood] = useState("");
  const [crawlMinBeds, setCrawlMinBeds] = useState("");
  const [crawlMinBaths, setCrawlMinBaths] = useState("");
  const [crawlMaxPrice, setCrawlMaxPrice] = useState("");
  const [crawlMinPrice, setCrawlMinPrice] = useState(config.defaultMinPrice);

  const [viewMode, setViewMode] = useState<"list" | "map">("list");
  const [mapListings, setMapListings] = useState<MapListing[]>([]);

  const [modalListingId, setModalListingId] = useState<number | null>(null);

  const [savedSearches, setSavedSearches] = useState<SavedSearch[]>([]);
  const [showSaveForm, setShowSaveForm] = useState(false);
  const [saveName, setSaveName] = useState("");

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const thumbPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const lt = config.listingType;

  const fetchListings = useCallback(async (p?: number) => {
    try {
      const params = new URLSearchParams();
      params.set("listing_type", lt);
      if (filterSource) params.set("source", filterSource);
      if (filterMaxPrice) params.set("max_price", filterMaxPrice);
      if (filterMinBeds) params.set("min_beds", filterMinBeds);
      if (filterStatus) params.set("status", filterStatus);
      if (filterFavorites) params.set("is_favorite", "true");
      if (sortBy) params.set("sort", sortBy);
      params.set("page", String(p ?? page));
      params.set("per_page", String(PER_PAGE));
      const res = await fetch(`/api/listings?${params.toString()}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PaginatedResponse = await res.json();
      setListings(data.listings);
      setTotal(data.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load listings");
    } finally {
      setLoading(false);
    }
  }, [lt, filterSource, filterMaxPrice, filterMinBeds, filterStatus, filterFavorites, sortBy, page]);

  const fetchMeta = useCallback(async () => {
    try {
      const [srcRes, statRes] = await Promise.all([
        fetch(`/api/sources?listing_type=${lt}`),
        fetch(`/api/stats?listing_type=${lt}`),
      ]);
      if (srcRes.ok) setSources(await srcRes.json());
      if (statRes.ok) setStats(await statRes.json());
    } catch { /* non-critical */ }
  }, [lt]);

  const fetchCrawlStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/crawl/status");
      if (res.ok) setCrawlStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  const fetchMapListings = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      params.set("listing_type", lt);
      if (filterSource) params.set("source", filterSource);
      if (filterMaxPrice) params.set("max_price", filterMaxPrice);
      if (filterMinBeds) params.set("min_beds", filterMinBeds);
      if (filterStatus) params.set("status", filterStatus);
      if (filterFavorites) params.set("is_favorite", "true");
      const res = await fetch(`/api/listings/map?${params.toString()}`);
      if (res.ok) setMapListings(await res.json());
    } catch { /* ignore */ }
  }, [lt, filterSource, filterMaxPrice, filterMinBeds, filterStatus, filterFavorites]);

  const fetchSavedSearches = useCallback(async () => {
    try {
      const res = await fetch(`/api/saved-searches?listing_type=${lt}`);
      if (res.ok) setSavedSearches(await res.json());
    } catch { /* ignore */ }
  }, [lt]);

  const fetchLocations = useCallback(async () => {
    try {
      const res = await fetch("/api/locations");
      if (res.ok) setLocationCatalog(await res.json());
    } catch { /* ignore */ }
  }, []);

  const neighborhoodsInBorough = useMemo<Neighborhood[]>(
    () => locationCatalog.neighborhoods.filter((n) => n.borough === crawlBorough),
    [locationCatalog.neighborhoods, crawlBorough],
  );

  const handleBoroughChange = (b: string) => {
    setCrawlBorough(b);
    setCrawlNeighborhood("");
  };

  const currentFilters = (): SavedSearch["filters"] => ({
    source: filterSource || undefined,
    max_price: filterMaxPrice || undefined,
    min_beds: filterMinBeds || undefined,
    status: filterStatus || undefined,
    is_favorite: filterFavorites || undefined,
    sort: sortBy || undefined,
  });

  const applySavedSearch = (saved: SavedSearch) => {
    const f = saved.filters ?? {};
    setFilterSource(f.source ?? "");
    setFilterMaxPrice(f.max_price ?? "");
    setFilterMinBeds(f.min_beds ?? "");
    setFilterStatus(f.status ?? "");
    setFilterFavorites(!!f.is_favorite);
    setSortBy(f.sort ?? "date_listed");
    setPage(1);
    fetch(`/api/saved-searches/${saved.id}/use`, { method: "POST" })
      .then(() => fetchSavedSearches())
      .catch(() => undefined);
  };

  const saveCurrentSearch = async () => {
    const name = saveName.trim();
    if (!name) return;
    try {
      const res = await fetch("/api/saved-searches", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          listing_type: lt,
          filters: currentFilters(),
        }),
      });
      if (res.ok) {
        setSaveName("");
        setShowSaveForm(false);
        fetchSavedSearches();
      }
    } catch { /* ignore */ }
  };

  const deleteSavedSearch = async (id: number) => {
    try {
      await fetch(`/api/saved-searches/${id}`, { method: "DELETE" });
      fetchSavedSearches();
    } catch { /* ignore */ }
  };

  useEffect(() => {
    fetchListings();
    fetchMeta();
    fetchCrawlStatus();
    fetchSavedSearches();
    fetchLocations();
  }, [fetchListings, fetchMeta, fetchCrawlStatus, fetchSavedSearches, fetchLocations]);

  useEffect(() => {
    if (viewMode === "map") fetchMapListings();
  }, [viewMode, fetchMapListings]);

  const handleFilterApply = () => {
    setPage(1);
    fetchListings(1);
    if (viewMode === "map") fetchMapListings();
  };

  const isRunning = crawlStatus?.status === "running";
  const isActive = crawlStatus?.status === "running" || crawlStatus?.status === "pending";

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
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [isActive, fetchCrawlStatus, fetchListings, fetchMeta]);

  useEffect(() => {
    thumbPollRef.current = setInterval(() => { fetchListings(); }, 8000);
    return () => { if (thumbPollRef.current) clearInterval(thumbPollRef.current); };
  }, [fetchListings]);

  const toggleSpider = (name: string, on: boolean) => {
    setSelectedSpiders((prev) => {
      const next = new Set(prev);
      on ? next.add(name) : next.delete(name);
      return next;
    });
  };

  const startCrawl = async () => {
    if (selectedSpiders.size === 0) return;
    if (!crawlBorough) {
      setError("Pick a borough before starting a crawl");
      return;
    }
    setStarting(true);
    const toIntOrNull = (s: string): number | null => {
      const n = parseInt(s, 10);
      return Number.isFinite(n) ? n : null;
    };
    const toFloatOrNull = (s: string): number | null => {
      const n = parseFloat(s);
      return Number.isFinite(n) ? n : null;
    };
    try {
      const res = await fetch("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spiders: [...selectedSpiders],
          max_pages: parseInt(maxPages) || 50,
          listing_type: lt,
          location: {
            borough: crawlBorough,
            neighborhood: crawlNeighborhood || null,
          },
          filters: {
            min_beds: toIntOrNull(crawlMinBeds),
            min_baths: toFloatOrNull(crawlMinBaths),
            max_price: toIntOrNull(crawlMaxPrice),
            min_price: toIntOrNull(crawlMinPrice),
          },
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

  const toggleFavorite = async (e: React.MouseEvent, listing: Listing) => {
    e.stopPropagation();
    e.preventDefault();
    try {
      await fetch(`/api/listings/${listing.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_favorite: listing.is_favorite ? 0 : 1 }),
      });
      fetchListings();
    } catch { /* ignore */ }
  };

  const handlePageChange = (p: number) => {
    setPage(p);
    fetchListings(p);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const totalMax = (crawlStatus?.max_pages ?? 50) * (crawlStatus?.spiders?.length ?? 1);
  const pct = totalMax > 0 ? ((crawlStatus?.pages_crawled ?? 0) / totalMax) * 100 : 0;

  return (
    <div style={s.page}>
      <header style={s.header}>
        <div style={s.headerInner}>
          <img src="/logo.png" alt="Rent Lobster" style={s.headerLogo} />
          <h1 style={s.title}>{config.title}</h1>
          <p style={s.subtitle}>{config.subtitle}</p>
        </div>
      </header>

      <main style={s.main}>
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

          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "center",
              gap: 12,
              marginTop: 12,
            }}
          >
            <label style={s.inlineLabel}>
              Borough
              <select
                style={{ ...s.select, minWidth: 140 }}
                value={crawlBorough}
                onChange={(e) => handleBoroughChange(e.target.value)}
              >
                {locationCatalog.boroughs.length === 0 ? (
                  <option value="brooklyn">Brooklyn</option>
                ) : (
                  locationCatalog.boroughs.map((b: Borough) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))
                )}
              </select>
            </label>
            <label style={s.inlineLabel}>
              Neighborhood
              <select
                style={{ ...s.select, minWidth: 180 }}
                value={crawlNeighborhood}
                onChange={(e) => setCrawlNeighborhood(e.target.value)}
              >
                <option value="">All in borough</option>
                {neighborhoodsInBorough.map((n) => (
                  <option key={n.id} value={n.id}>{n.name}</option>
                ))}
              </select>
            </label>
            <label style={s.inlineLabel}>
              Min beds
              <input
                type="number"
                min={0}
                max={10}
                value={crawlMinBeds}
                onChange={(e) => setCrawlMinBeds(e.target.value)}
                style={{ ...s.input, width: 70 }}
              />
            </label>
            <label style={s.inlineLabel}>
              Min baths
              <input
                type="number"
                min={0}
                max={10}
                step={0.5}
                value={crawlMinBaths}
                onChange={(e) => setCrawlMinBaths(e.target.value)}
                style={{ ...s.input, width: 70 }}
              />
            </label>
            <label style={s.inlineLabel}>
              {config.minPriceLabel}
              <input
                type="number"
                min={0}
                placeholder={config.listingType === "sale" ? "50000" : "0"}
                value={crawlMinPrice}
                onChange={(e) => setCrawlMinPrice(e.target.value)}
                style={{ ...s.input, width: 110 }}
              />
            </label>
            <label style={s.inlineLabel}>
              {config.priceLabel}
              <input
                type="number"
                min={0}
                placeholder={config.listingType === "sale" ? "1500000" : "4500"}
                value={crawlMaxPrice}
                onChange={(e) => setCrawlMaxPrice(e.target.value)}
                style={{ ...s.input, width: 110 }}
              />
            </label>
          </div>

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
                  Crawl completed &mdash; {crawlStatus.pages_crawled} pages processed, {crawlStatus.listings_found} listings found.
                </div>
              )}
              {crawlStatus.status === "error" && (
                <div style={s.crawlError}>Crawl failed: {crawlStatus.error}</div>
              )}
            </div>
          )}
        </section>

        {stats && stats.total > 0 && (
          <section style={s.statsRow}>
            <StatCard label="Total Listings" value={String(stats.total)} />
            <StatCard label="Sources" value={String(stats.sources)} />
            <StatCard
              label="Avg Price"
              value={stats.avg_price ? formatPrice(Math.round(stats.avg_price)) : "\u2014"}
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

        <SavedSearchesBar
          searches={savedSearches}
          onApply={applySavedSearch}
          onDelete={deleteSavedSearch}
        />

        <section style={s.filters}>
          <select style={s.select} value={filterSource} onChange={(e) => setFilterSource(e.target.value)}>
            <option value="">All Sources</option>
            {sources.map((src) => (
              <option key={src} value={src}>{src}</option>
            ))}
          </select>
          <input
            style={s.input}
            type="number"
            placeholder={config.priceLabel}
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
          <select style={s.select} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
            <option value="">All Statuses</option>
            <option value="new">New</option>
            <option value="seen">Seen</option>
            <option value="applied">{config.appliedLabel}</option>
          </select>
          <Checkbox label="Favorites only" checked={filterFavorites} onChange={setFilterFavorites} />
          <select style={s.select} value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="date_listed">Newest Listed</option>
            <option value="created_at">Recently Added</option>
            <option value="price_asc">Price: Low to High</option>
            <option value="price_desc">Price: High to Low</option>
          </select>
          <button style={s.button} onClick={handleFilterApply}>Apply</button>
          {showSaveForm ? (
            <div style={savedStyles.saveForm}>
              <input
                autoFocus
                style={s.input}
                placeholder="Search name"
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveCurrentSearch();
                  if (e.key === "Escape") { setShowSaveForm(false); setSaveName(""); }
                }}
              />
              <button style={s.button} onClick={saveCurrentSearch}>Save</button>
              <button
                style={savedStyles.linkButton}
                onClick={() => { setShowSaveForm(false); setSaveName(""); }}
              >
                Cancel
              </button>
            </div>
          ) : (
            <button style={savedStyles.secondaryButton} onClick={() => setShowSaveForm(true)}>
              Save search
            </button>
          )}
        </section>

        {error && <p style={s.errorMsg}>{error}</p>}

        <div style={s.viewToggle}>
          <div style={s.resultsMeta}>
            <span style={{ color: "#6b7280", fontSize: 14 }}>
              {total} listing{total !== 1 ? "s" : ""} found
              {viewMode === "list" && totalPages > 1 ? ` \u2014 page ${page} of ${totalPages}` : ""}
              {viewMode === "map" ? ` \u00b7 ${mapListings.length} on map` : ""}
            </span>
          </div>
          <div style={s.toggleBtns}>
            <button
              style={{ ...s.toggleBtn, ...(viewMode === "list" ? s.toggleBtnActive : {}) }}
              onClick={() => setViewMode("list")}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" />
              </svg>
              List
            </button>
            <button
              style={{ ...s.toggleBtn, ...(viewMode === "map" ? s.toggleBtnActive : {}) }}
              onClick={() => setViewMode("map")}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              Map
            </button>
          </div>
        </div>

        {loading ? (
          <p style={s.loadingMsg}>Loading listings...</p>
        ) : viewMode === "map" ? (
          <ListingsMap
            markers={mapListings}
            onMarkerClick={(id: number) => setModalListingId(id)}
            showNoFee={config.showNoFee}
          />
        ) : listings.length === 0 ? (
          <div style={s.empty}>
            <p style={{ fontSize: 18, color: "#6b7280" }}>
              No listings found. Start a crawl above or run <code>make run</code> from the terminal.
            </p>
          </div>
        ) : (
          <>
            <div style={s.grid}>
              {listings.map((listing) => {
                const status = getStatus(listing);
                return (
                  <div
                    key={listing.id}
                    style={s.card}
                    onClick={() => setModalListingId(listing.id)}
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
                    <div style={{ position: "relative" as const }}>
                      <Thumbnail thumbnailPath={listing.thumbnail_path} />
                      <div style={s.cardOverlay}>
                        <StarButton active={!!listing.is_favorite} onClick={(e) => toggleFavorite(e, listing)} />
                      </div>
                      {config.showNoFee && listing.no_fee ? (
                        <span style={s.noFeeBadge}>No Fee</span>
                      ) : null}
                      {config.showHoa && listing.hoa_fee ? (
                        <span style={{ ...s.noFeeBadge, backgroundColor: "#0369a1" }}>
                          HOA ${listing.hoa_fee.toLocaleString()}/mo
                        </span>
                      ) : null}
                    </div>

                    <div style={s.cardHeader}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <SourceBadge source={listing.source} />
                        <StatusDot status={status} />
                      </div>
                      <span style={s.price}>{formatPrice(listing.price)}</span>
                    </div>

                    <div style={s.cardBody}>
                      {listing.address && <p style={s.address}>{listing.address}</p>}
                      {listing.neighborhood && <p style={s.neighborhood}>{listing.neighborhood}</p>}
                      <div style={s.details}>
                        {listing.beds !== null && <span style={s.detail}>{listing.beds} bed</span>}
                        {listing.baths !== null && <span style={s.detail}>{listing.baths} bath</span>}
                        {listing.sqft !== null && <span style={s.detail}>{listing.sqft} sqft</span>}
                        {config.showHoa && listing.property_type && (
                          <span style={s.detail}>{listing.property_type}</span>
                        )}
                      </div>
                      <AmenityChips listing={listing} labels={config.amenityLabels} />
                    </div>

                    <div style={s.cardFooter}>
                      <span>
                        {listing.date_listed
                          ? `Listed ${new Date(listing.date_listed).toLocaleDateString()}`
                          : new Date(listing.created_at).toLocaleDateString()}
                      </span>
                      <span style={s.linkText}>Details &rarr;</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <Pagination page={page} totalPages={totalPages} onPageChange={handlePageChange} />
          </>
        )}
      </main>

      {modalListingId !== null && (
        <DetailModal
          listingId={modalListingId}
          onClose={() => setModalListingId(null)}
          onUpdate={() => fetchListings()}
          config={config}
        />
      )}
    </div>
  );
}
