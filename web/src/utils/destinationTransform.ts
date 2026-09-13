import type { Destination } from '@/types/destination';
import type { MapCityPoint } from '@/constants/chinaGeo';
import { projectToSvg } from '@/constants/chinaGeo';

/**
 * Transform API Destination to MapCityPoint for map rendering
 */
export function transformDestinationToMapPoint(dest: Destination): MapCityPoint | null {
  if (!dest.coordinates) {
    return null;
  }

  const { latitude, longitude } = dest.coordinates;
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return null;
  const { x, y } = projectToSvg(longitude, latitude);

  return {
    name: dest.name,
    enName: dest.nameEn || '',
    lng: longitude,
    lat: latitude,
    x,
    y,
    tag: dest.tagline || '',
    desc: dest.description,
    iata: dest.iataCode,
    region: dest.region || null,
  };
}

/**
 * Transform array of Destinations to MapCityPoint array, filtering out invalid entries
 */
export function transformDestinationsToMapPoints(destinations: Destination[]): MapCityPoint[] {
  return destinations
    .map(transformDestinationToMapPoint)
    .filter((point): point is MapCityPoint => point !== null);
}

/**
 * Alias for backward compatibility
 */
export const destinationsToMapPoints = transformDestinationsToMapPoints;
