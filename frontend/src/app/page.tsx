"use client";

import ListingFinder from "@/components/ListingFinder";
import { RENTAL_CONFIG } from "@/configs";

export default function Home() {
  return <ListingFinder config={RENTAL_CONFIG} />;
}
