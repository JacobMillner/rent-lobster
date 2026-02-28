export interface Listing {
  id: number;
  source: string;
  url: string;
  listing_type: string;
  price: number | null;
  beds: number | null;
  baths: number | null;
  address: string | null;
  neighborhood: string | null;
  thumbnail_path: string | null;
  created_at: string;
  sqft: number | null;
  description: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  subway_minutes: number | null;
  nearest_subway: string | null;
  has_dishwasher: number | null;
  has_balcony: number | null;
  laundry: string | null;
  has_doorman: number | null;
  has_elevator: number | null;
  has_gym: number | null;
  pets_allowed: number | null;
  no_fee: number | null;
  available_date: string | null;
  floor: string | null;
  date_listed: string | null;
  latitude: number | null;
  longitude: number | null;
  status: string | null;
  is_favorite: number | null;
  notes: string | null;
  hoa_fee: number | null;
  year_built: number | null;
  property_type: string | null;
  tax_annual: number | null;
}

export interface PaginatedResponse {
  listings: Listing[];
  total: number;
  page: number;
  per_page: number;
}

export interface Stats {
  total: number;
  sources: number;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
}

export interface CrawlStatus {
  id?: string;
  status: string;
  listing_type?: string;
  spiders?: string[];
  max_pages?: number;
  pages_crawled?: number;
  listings_found?: number;
  current_spider?: string | null;
  error?: string | null;
}

export interface MapListing {
  id: number;
  latitude: number;
  longitude: number;
  price: number | null;
  address: string | null;
  beds: number | null;
  baths: number | null;
  thumbnail_path: string | null;
  neighborhood: string | null;
  no_fee: number | null;
  source: string;
}

export interface ListingFinderConfig {
  listingType: "rental" | "sale";
  title: string;
  subtitle: string;
  priceLabel: string;
  showNoFee: boolean;
  showHoa: boolean;
  appliedLabel: string;
  appliedActiveLabel: string;
  editableFields: { key: keyof Listing; label: string; type: string }[];
  amenityLabels: Record<string, string>;
}
