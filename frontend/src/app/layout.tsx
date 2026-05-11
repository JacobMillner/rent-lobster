import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Rent Lobster",
  description: "Apartment rental and real estate listing aggregator",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, -apple-system, sans-serif" }}>
        <nav
          style={{
            display: "flex",
            alignItems: "center",
            gap: 24,
            padding: "10px 24px",
            backgroundColor: "#111827",
            color: "white",
            fontSize: 14,
            fontWeight: 500,
          }}
        >
          <a href="/" style={navLink}>Rentals</a>
          <a href="/buy" style={navLink}>Buy</a>
          <a href="/trends" style={navLink}>Trends</a>
        </nav>
        {children}
      </body>
    </html>
  );
}

const navLink: React.CSSProperties = {
  color: "rgba(255,255,255,0.85)",
  textDecoration: "none",
  padding: "6px 12px",
  borderRadius: 6,
  transition: "background 0.15s",
};
