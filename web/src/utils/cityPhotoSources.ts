import type { Destination } from '@/types/destination';
import { CITY_NAME_TO_FOLDER, getCityAllCovers } from './cityPhotos';

export const CITY_PLACEHOLDER = '/city-placeholder.svg';

/** Use the existing city-specific CDN gallery; never substitute another city. */
export function cityPhotoSources(city: string, destination?: Destination): string[] {
  const name = city.trim().replace(/市$/, '');
  const gallery = CITY_NAME_TO_FOLDER[name] ? getCityAllCovers(name) : [];
  const supplied = [destination?.backgroundImageUrl, destination?.coverImageUrl,
    ...(destination?.referenceImages?.map(image => image.url) ?? [])];
  const photos = [...supplied, ...gallery].filter((url): url is string =>
    typeof url === 'string' && Boolean(url) && !url.includes('city-placeholder.svg'));
  return photos.length ? [...new Set(photos)] : [CITY_PLACEHOLDER];
}
