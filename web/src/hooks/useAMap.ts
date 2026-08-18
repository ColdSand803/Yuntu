import { useEffect, useRef, useState } from "react";
import AMapLoader from "@amap/amap-jsapi-loader";

interface UseAMapOptions {
  containerId: string;
  zoom?: number;
  center?: [number, number];
}

export function useAMap({ containerId, zoom = 12, center }: UseAMapOptions) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const mapRef = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let destroyed = false;

    AMapLoader.load({
      key: import.meta.env.VITE_AMAP_KEY || "",
      version: "2.0",
    })
      .then((AMap) => {
        if (destroyed) return;
        const container = document.getElementById(containerId);
        if (!container) return;

        mapRef.current = new AMap.Map(containerId, {
          zoom,
          center,
          viewMode: "2D",
        });
        setReady(true);
      })
      .catch((err: Error) => {
        if (!destroyed) setError(err);
      });

    return () => {
      destroyed = true;
      mapRef.current?.destroy();
    };
  }, [containerId, zoom, center]);

  return { map: mapRef, ready, error };
}
