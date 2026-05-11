"use client";

import ListingFinder from "@/components/ListingFinder";
import { SALE_CONFIG } from "@/configs";

export default function BuyPage() {
  return <ListingFinder config={SALE_CONFIG} />;
}
