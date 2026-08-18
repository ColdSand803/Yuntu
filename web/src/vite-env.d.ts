/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE: string;
  readonly VITE_USE_MOCK: string;
  readonly VITE_CITY_ASSET_BASE_URL: string;
  readonly VITE_AMAP_KEY: string;
  readonly VITE_AMAP_SECURITY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
