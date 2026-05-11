"use client";

import { useEffect, useState } from "react";
import type { Listing } from "@/types";
import { s } from "@/styles";

export const SOURCE_COLORS: Record<string, string> = {
  craigslist: "#6b21a8",
  streeteasy: "#0369a1",
  zillow: "#0e7490",
};

export const STATUS_COLORS: Record<string, string> = {
  new: "#22c55e",
  seen: "#eab308",
  applied: "#3b82f6",
};

export function formatPrice(price: number | null): string {
  if (price === null || price === undefined) return "\u2014";
  return `$${price.toLocaleString()}`;
}

export function getStatus(listing: Pick<Listing, "status">): string {
  return listing.status || "new";
}

export function SourceBadge({ source }: { source: string }) {
  const bg = SOURCE_COLORS[source] ?? "#374151";
  return <span style={{ ...s.badge, backgroundColor: bg }}>{source}</span>;
}

export function StatusDot({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.new;
  return (
    <span
      style={{ ...s.statusDot, backgroundColor: color }}
      title={status.charAt(0).toUpperCase() + status.slice(1)}
    />
  );
}

export function StarButton({
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

export function Thumbnail({
  thumbnailPath,
  height,
}: {
  thumbnailPath: string | null | undefined;
  height?: number;
}) {
  const [err, setErr] = useState(false);
  const style = height ? { ...s.thumbImg, height } : s.thumbImg;
  const placeholderStyle = height
    ? { ...s.thumbPlaceholder, height }
    : s.thumbPlaceholder;

  if (!thumbnailPath || err) {
    return (
      <div style={placeholderStyle}>
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
      src={`/api/thumbnails/${thumbnailPath}`}
      alt=""
      style={style}
      onError={() => setErr(true)}
    />
  );
}

/** Keyboard navigation helper used by the gallery in DetailModal. */
export function useArrowKeyNav(length: number, setIdx: (fn: (i: number) => number) => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (length <= 1) return;
      if (e.key === "ArrowLeft") setIdx((i) => (i - 1 + length) % length);
      if (e.key === "ArrowRight") setIdx((i) => (i + 1) % length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [length, setIdx]);
}
