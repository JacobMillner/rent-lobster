"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Listing, ListingFinderConfig } from "@/types";
import { s } from "@/styles";
import {
  SourceBadge,
  StarButton,
  StatusDot,
  Thumbnail,
  formatPrice,
  getStatus,
  useArrowKeyNav,
} from "./listingShared";

function ImageGallery({ listing }: { listing: Listing }) {
  const images = (listing.images ?? []).filter((img) => img.image_path);
  const [idx, setIdx] = useState(0);
  const [imgErr, setImgErr] = useState<Set<number>>(new Set());

  useArrowKeyNav(images.length, setIdx);

  if (images.length === 0) {
    return (
      <div style={s.modalImgWrap}>
        <Thumbnail thumbnailPath={listing.thumbnail_path} />
      </div>
    );
  }

  const safeIdx = idx < images.length ? idx : 0;
  const current = images[safeIdx];
  const maxDots = 12;

  return (
    <div style={s.galleryWrap}>
      {imgErr.has(safeIdx) ? (
        <div style={{ ...s.thumbPlaceholder, height: 400 }}>
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#cbd5e1" strokeWidth="1.5">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="m21 15-5-5L5 21" />
          </svg>
        </div>
      ) : (
        <img
          src={`/api/images/${current.image_path}`}
          alt={`Photo ${safeIdx + 1}`}
          style={s.galleryImg}
          onError={() => setImgErr((prev) => new Set(prev).add(safeIdx))}
        />
      )}

      {images.length > 1 && (
        <>
          <button
            style={{ ...s.galleryArrow, ...s.galleryArrowLeft }}
            onClick={(e) => { e.stopPropagation(); setIdx((i) => (i - 1 + images.length) % images.length); }}
            aria-label="Previous image"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <button
            style={{ ...s.galleryArrow, ...s.galleryArrowRight }}
            onClick={(e) => { e.stopPropagation(); setIdx((i) => (i + 1) % images.length); }}
            aria-label="Next image"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </button>
        </>
      )}

      <span style={s.galleryCounter}>
        {safeIdx + 1} / {images.length}
      </span>

      {images.length > 1 && images.length <= maxDots && (
        <div style={s.galleryDots}>
          {images.map((_, i) => (
            <button
              key={i}
              style={{ ...s.galleryDot, ...(i === safeIdx ? s.galleryDotActive : {}) }}
              onClick={(e) => { e.stopPropagation(); setIdx(i); }}
              aria-label={`Go to image ${i + 1}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

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

export default function DetailModal({
  listingId,
  onClose,
  onUpdate,
  config,
}: {
  listingId: number;
  onClose: () => void;
  onUpdate?: () => void;
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
        onUpdate?.();
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

        <ImageGallery listing={listing} />

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
