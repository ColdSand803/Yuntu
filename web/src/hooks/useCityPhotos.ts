import { useDestinations } from './useDestinations';
import { cityPhotoSources } from '@/utils/cityPhotoSources';
export { CITY_PLACEHOLDER } from '@/utils/cityPhotoSources';
export function useCityPhotos(city: string): string[] {
  const { data } = useDestinations();
  const destination = data?.destinations.find(d => d.name === city);
  return cityPhotoSources(city, destination);
}
