export const CITY_ASSET_CDN_BASE_URL = "";

const configuredCityAssetBaseUrl = (
  import.meta.env.VITE_CITY_ASSET_BASE_URL ?? CITY_ASSET_CDN_BASE_URL
)
  .trim()
  .replace(/\/+$/, "");

/**
 * Prefix a city image path with the configured CDN origin.
 *
 * Production and normal development are CDN-only. An explicit baseUrl
 * argument is retained solely for deterministic helper tests.
 */
export function withCityAssetBase(
  path: string,
  baseUrl = configuredCityAssetBaseUrl,
): string {
  if (!path.startsWith("/city/") && !path.startsWith("/city-opt/")) {
    return path;
  }

  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
  return normalizedBaseUrl ? `${normalizedBaseUrl}${path}` : path;
}

/** Return the path portion of either a same-origin or absolute asset URL. */
export function cityAssetPathname(url: string): string | null {
  if (url.startsWith("/")) return url;

  try {
    return new URL(url).pathname;
  } catch {
    return null;
  }
}

export function resolveCityAssetVariant(
  url: string,
  options: {
    mobile?: boolean;
    format?: "jpg" | "webp";
  } = {},
): string {
  const pathname = cityAssetPathname(url);
  if (!pathname?.startsWith("/city/") || !pathname.endsWith(".jpg")) {
    return url;
  }

  const suffix = options.mobile ? ".mobile" : "";
  const format = options.format ?? "webp";
  const optimizedPath = pathname
    .replace("/city/", "/city-opt/")
    .replace(".jpg", `${suffix}.${format}`);

  return withCityAssetBase(optimizedPath);
}
