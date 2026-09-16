import { useQuery } from '@tanstack/react-query';
import type { DestinationsResponse } from '@/types/destination';
import { fetchDestinations } from '@/services/api';

/**
 * React Query hook for fetching destinations from API
 * Implements automatic retry with exponential backoff
 */
export function useDestinations() {
  return useQuery({
    queryKey: ['destinations'],
    queryFn: async () => {
      const result = await fetchDestinations();
      try { sessionStorage.setItem('yuntu:destinations:v2', JSON.stringify(result)); } catch { /* Storage may be disabled. */ }
      return result;
    },
    placeholderData: () => {
      try {
        const cached = JSON.parse(sessionStorage.getItem('yuntu:destinations:v2') || 'null') as DestinationsResponse | null;
        if (cached && Array.isArray(cached.destinations) && cached.destinations.every(d => typeof d?.id === 'string' && typeof d?.name === 'string')) return cached;
      } catch { /* Invalid or unavailable storage is ignored; HTTP still runs. */ }
      return undefined;
    },
    staleTime: 1000 * 30, // Revalidate mounted consumers after 30 seconds.
    gcTime: 1000 * 60 * 30, // 30 minutes (formerly cacheTime)
    retry: 1,
    retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
  });
}
