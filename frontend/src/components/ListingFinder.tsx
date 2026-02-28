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
} from "@/types";
import { s } from "@/styles";

const ALL_SPIDERS = ["craigslist", "streeteasy", "zillow"] as const;
const PER_PAGE = 24;

const SOURCE_COLORS: Record<string, string> = {
  craigslist: "#6b21a8",
  streeteasy: "#0369a1",
  zillow: "#0e7490",
};

const STATUS_COLORS: Record<string, string> = {
  new: "#22c55e",
  seen: "#eab308",
  applied: "#3b82f6",
};

function formatPrice(price: number | null): string {
  if (price === null) return "\u2014";
  return `$${price.toLocaleString()}`;
}

function getStatus(listing: Listing): string {
  return listing.status || "new";
}

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

function SourceBadge({ source }: { source: string }) {
  const bg = SOURCE_COLORS[source] ?? "#374151";
  return <span style={{ ...s.badge, backgroundColor: bg }}>{source}</span>;
}

function StatusDot({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.new;
  return (
    <span
      style={{ ...s.statusDot, backgroundColor: color }}
      title={status.charAt(0).toUpperCase() + status.slice(1)}
    />
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

function StarButton({
  active,
  onClick,
}: {
  active: boolean;
  onClick: (e: React.MouseEvent) => void;
}) {
  return (
    <button onClick={onClick} style={s.starBtn} title={active ? "Unfavorite" : "Favorite"}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill={active ? "#eab308" : "none"} stroke={active ? "#eab308" : "#9ca3af"} strokeWidth="2">
        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
      </svg>
    </button>
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

function EditableField({
  label,
  value,
  type,
  onSave,
}: {
  label: string;
  value: string | number | null;
  type: string;
  onSave: (val: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value ?? ""));

  const commit = () => {
    setEditing(false);
    if (draft !== String(value ?? "")) {
      onSave(draft);
    }
  };

  if (editing) {
    return (
      <div style={s.editFieldRow}>
        <span style={s.editFieldLabel}>{label}</span>
        <input
          autoFocus
          type={type}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => { if (e.key === "Enter") commit(); if (e.key === "Escape") setEditing(false); }}
          style={s.editFieldInput}
        />
      </div>
    );
  }

  return (
    <div style={s.editFieldRow}>
      <span style={s.editFieldLabel}>{label}</span>
      <span style={s.editFieldValue}>
        {value !== null && value !== undefined && value !== "" ? String(value) : "\u2014"}
        <button
          style={s.editPencilBtn}
          onClick={() => { setDraft(String(value ?? "")); setEditing(true); }}
          title="Edit"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
        </button>
      </span>
    </div>
  );
}

function DetailModal({
  listingId,
  onClose,
  onUpdate,
  config,
}: {
  listingId: number;
  onClose: () => void;
  onUpdate: () => void;
  config: ListingFinderConfig;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const notesTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchDetail = useCallback(async () => {
    try {
      const res = await fetch(`/api/listings/${listingId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Listing = await res.json();
      setListing(data);
      setNotes(data.notes ?? "");
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : "Failed to load");
    }
  }, [listingId]);

  useEffect(() => { fetchDetail(); }, [fetchDetail]);

  const patchField = async (fields: Record<string, unknown>) => {
    try {
      const res = await fetch(`/api/listings/${listingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (res.ok) {
        const updated: Listing = await res.json();
        setListing(updated);
        onUpdate();
      }
    } catch { /* ignore */ }
  };

  const handleNotesChange = (val: string) => {
    setNotes(val);
    if (notesTimer.current) clearTimeout(notesTimer.current);
    notesTimer.current = setTimeout(() => patchField({ notes: val }), 800);
  };

  const toggleFavorite = () => {
    if (!listing) return;
    patchField({ is_favorite: listing.is_favorite ? 0 : 1 });
  };

  const setStatus = (newStatus: string) => {
    patchField({ status: newStatus });
  };

  const handleAmenityToggle = (key: string, current: number | null) => {
    patchField({ [key]: current ? 0 : 1 });
  };

  const handleLaundryChange = (val: string) => {
    patchField({ laundry: val || null });
  };

  if (loadErr) {
    return (
      <div style={s.modalOverlay} onClick={onClose}>
        <div style={s.modalCard} onClick={(e) => e.stopPropagation()}>
          <p style={{ color: "#dc2626", padding: 20 }}>Error: {loadErr}</p>
        </div>
      </div>
    );
  }

  if (!listing) {
    return (
      <div style={s.modalOverlay}>
        <div style={s.modalCard}>
          <p style={{ textAlign: "center", padding: 40, color: "#6b7280" }}>Loading...</p>
        </div>
      </div>
    );
  }

  const status = getStatus(listing);

  return (
    <div style={s.modalOverlay} onClick={onClose}>
      <div style={s.modalCard} onClick={(e) => e.stopPropagation()}>
        <button style={s.modalClose} onClick={onClose}>&times;</button>

        <div style={s.modalImgWrap}>
          <Thumbnail listing={listing} />
        </div>

        <div style={s.modalHeader}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <SourceBadge source={listing.source} />
            <StatusDot status={status} />
            <span style={{ fontSize: 13, color: "#6b7280", textTransform: "capitalize" as const }}>{status}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 26, fontWeight: 700, color: "#111827" }}>
              {formatPrice(listing.price)}
            </span>
            <StarButton active={!!listing.is_favorite} onClick={toggleFavorite} />
          </div>
        </div>

        <div style={s.modalBody}>
          <div style={s.modalActions}>
            <button
              style={{ ...s.actionBtn, ...(status === "seen" ? s.actionBtnActive : {}) }}
              onClick={() => setStatus(status === "seen" ? "new" : "seen")}
            >
              {status === "seen" ? "Marked Seen" : "Mark as Seen"}
            </button>
            <button
              style={{
                ...s.actionBtn,
                backgroundColor: status === "applied" ? "#3b82f6" : undefined,
                color: status === "applied" ? "white" : undefined,
              }}
              onClick={() => setStatus(status === "applied" ? "new" : "applied")}
            >
              {status === "applied" ? config.appliedActiveLabel : config.appliedLabel}
            </button>
            <a href={listing.url} target="_blank" rel="noopener noreferrer" style={s.actionBtnLink}>
              View Original &rarr;
            </a>
          </div>

          <div style={s.modalSection}>
            <h3 style={s.modalSectionTitle}>Details</h3>
            <div style={s.editFieldGrid}>
              {config.editableFields.map(({ key, label, type }) => (
                <EditableField
                  key={key}
                  label={label}
                  value={listing[key] as string | number | null}
                  type={type}
                  onSave={(val) => {
                    const parsed = type === "number" ? (val ? Number(val) : null) : (val || null);
                    patchField({ [key]: parsed });
                  }}
                />
              ))}
            </div>
          </div>

          <div style={s.modalSection}>
            <h3 style={s.modalSectionTitle}>Amenities</h3>
            <div style={s.amenityGrid}>
              {Object.entries(config.amenityLabels).map(([key, label]) => (
                <label key={key} style={s.amenityCheckLabel}>
                  <input
                    type="checkbox"
                    checked={!!(listing[key as keyof Listing])}
                    onChange={() => handleAmenityToggle(key, listing[key as keyof Listing] as number | null)}
                    style={s.checkbox}
                  />
                  {label}
                </label>
              ))}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 14, color: "#374151" }}>Laundry:</span>
                <select
                  value={listing.laundry ?? ""}
                  onChange={(e) => handleLaundryChange(e.target.value)}
                  style={{ ...s.select, minWidth: 120, padding: "6px 10px" }}
                >
                  <option value="">Unknown</option>
                  <option value="in_unit">In Unit</option>
                  <option value="in_building">In Building</option>
                </select>
              </div>
            </div>
          </div>

          {listing.description && (
            <div style={s.modalSection}>
              <h3 style={s.modalSectionTitle}>Description</h3>
              <p style={s.descriptionText}>{listing.description}</p>
            </div>
          )}

          <div style={s.modalSection}>
            <h3 style={s.modalSectionTitle}>Notes</h3>
            <textarea
              style={s.notesArea}
              value={notes}
              onChange={(e) => handleNotesChange(e.target.value)}
              placeholder="Add your personal notes here..."
              rows={4}
            />
          </div>
        </div>
      </div>
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

  const [viewMode, setViewMode] = useState<"list" | "map">("list");
  const [mapListings, setMapListings] = useState<MapListing[]>([]);

  const [modalListingId, setModalListingId] = useState<number | null>(null);

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

  useEffect(() => {
    fetchListings();
    fetchMeta();
    fetchCrawlStatus();
  }, [fetchListings, fetchMeta, fetchCrawlStatus]);

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
    setStarting(true);
    try {
      const res = await fetch("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spiders: [...selectedSpiders],
          max_pages: parseInt(maxPages) || 50,
          listing_type: lt,
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
                      <Thumbnail listing={listing} />
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
