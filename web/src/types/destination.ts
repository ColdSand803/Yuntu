/**
 * Destination type from BFF API /api/destinations
 */
export interface Destination {
  id: string;
  name: string;
  nameEn?: string;
  iataCode?: string;
  region?: string;
  tagline?: string;
  description?: string;
  coverImageUrl?: string;
  backgroundImageUrl?: string;
  referenceImages?: { url: string; placeId: number; placeName: string; assetId: string }[];
  mapLabelOffset?: { x: number; y: number };
  quality?: { canonical_pass: boolean | null; evidence_pass: boolean | null; last_check_at: string | null };
  coordinates?: {
    latitude: number;
    longitude: number;
  };
  tags?: string[];
  isActive?: boolean;
  createdAt?: string;
  updatedAt?: string;
}

/**
 * API response wrapper for destinations list
 */
export interface DestinationsResponse {
  destinations: Destination[];
  total: number;
  timestamp: string;
}
