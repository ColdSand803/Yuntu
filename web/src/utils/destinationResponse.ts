import type { Destination, DestinationsResponse } from '@/types/destination';

/** Validate and adapt the BFF wire contract once, at the HTTP boundary. */
export function parseDestinationsResponse(raw: unknown): DestinationsResponse {
  if (!raw || typeof raw !== 'object' || !('destinations' in raw) || !Array.isArray(raw.destinations)) {
    throw new Error('城市目录响应格式异常');
  }
  const destinations: Destination[] = raw.destinations.map((item: unknown) => {
    if (!item || typeof item !== 'object') throw new Error('城市目录数据异常');
    const d = item as Record<string, unknown>;
    if (typeof d.id !== 'string' || typeof d.name !== 'string' || !d.name.trim()) throw new Error('城市目录数据异常');
    const coords = d.coordinates as { lat?: unknown; lng?: unknown } | null;
    const valid = typeof coords?.lat === 'number' && Number.isFinite(coords.lat) && Math.abs(coords.lat) <= 90 &&
      typeof coords.lng === 'number' && Number.isFinite(coords.lng) && Math.abs(coords.lng) <= 180;
    const offset = d.map_label_offset as { x?: unknown; y?: unknown } | null;
    const tags = Array.isArray(d.tags) ? d.tags.filter((t): t is string => typeof t === 'string') : [];
    const quality = d.quality as Record<string, unknown> | null;
    return {
      id: d.id, name: d.name,
      nameEn: typeof d.en_name === 'string' ? d.en_name : '',
      iataCode: typeof d.iata === 'string' ? d.iata : '',
      region: typeof d.region === 'string' ? d.region : '',
      tags, tagline: tags.join(' · '),
      quality: quality ? {
        canonical_pass: typeof quality.canonical_pass === 'boolean' ? quality.canonical_pass : null,
        evidence_pass: typeof quality.evidence_pass === 'boolean' ? quality.evidence_pass : null,
        last_check_at: typeof quality.last_check_at === 'string' ? quality.last_check_at : null,
      } : undefined,
      referenceImages: Array.isArray(d.reference_images) ? d.reference_images.flatMap((image) => {
        if (!image || typeof image !== 'object') return [];
        const i = image as Record<string, unknown>;
        return typeof i.url === 'string' && typeof i.place_id === 'number' && typeof i.place_name === 'string'
          ? [{ url: i.url, placeId: i.place_id, placeName: i.place_name, assetId: String(i.asset_id ?? '') }] : [];
      }) : [],
      coverImageUrl: typeof d.card_cover_url === 'string' ? d.card_cover_url : undefined,
      backgroundImageUrl: typeof d.background_image_url === 'string' ? d.background_image_url : undefined,
      coordinates: valid ? { latitude: coords!.lat as number, longitude: coords!.lng as number } : undefined,
      mapLabelOffset: { x: typeof offset?.x === 'number' && Number.isFinite(offset.x) ? offset.x : 0,
        y: typeof offset?.y === 'number' && Number.isFinite(offset.y) ? offset.y : 0 },
      isActive: d.isActive !== false && d.is_active !== false,
    };
  });
  return { destinations, total: destinations.length, timestamp: 'cached_at' in raw && typeof raw.cached_at === 'string' ? raw.cached_at : '' };
}
