export interface ListingImage {
  id: number;
  image_path: string | null;
  position: number;
}

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
  images?: ListingImage[];
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

export interface SavedSearchFilters {
  source?: string;
  max_price?: string;
  min_beds?: string;
  status?: string;
  is_favorite?: boolean;
  sort?: string;
}

export interface SavedSearch {
  id: number;
  name: string;
  listing_type: string;
  filters: SavedSearchFilters;
  created_at: string;
  last_used_at: string | null;
}

export interface TrendSummary {
  listing_type: string;
  total: number;
  avg_price: number | null;
  median_price: number | null;
  min_price: number | null;
  max_price: number | null;
  median_price_per_sqft: number | null;
  avg_price_per_sqft: number | null;
  avg_hoa: number | null;
  avg_tax: number | null;
  beds_breakdown: { beds: number | null; count: number }[];
  property_type_breakdown: { property_type: string; count: number }[];
  price_distribution: { bin_start: number; bin_end: number; count: number }[];
}

export interface TrendNeighborhood {
  neighborhood: string;
  count: number;
  median_price: number | null;
  avg_price: number | null;
  min_price: number | null;
  max_price: number | null;
  median_price_per_sqft: number | null;
}

export interface TrendPricePoint {
  week: string;
  avg_price: number | null;
  sample_size: number;
}

export interface TrendVolumePoint {
  week: string;
  new_count: number;
  active_count: number;
}

export interface PriceDrop {
  id: number;
  url: string;
  source: string;
  address: string | null;
  neighborhood: string | null;
  beds: number | null;
  baths: number | null;
  thumbnail_path: string | null;
  latest_price: number;
  latest_at: string;
  prev_price: number;
  prev_at: string;
}
