import { useState, useEffect, useRef, useCallback } from "react";
import { X, Search, AlertCircle } from "lucide-react";
import { fetchPoiCatalog, SelectablePoi, checkPoiSelection } from "@/api/poi";
import { showToast } from "@/stores/toastStore";

interface CinematicPoiPickerProps {
  city: string;
  isOpen: boolean;
  selectedPois: { id: number; name: string }[];
  onClose: () => void;
  onSave: (pois: { id: number; name: string }[]) => void;
}

export function CinematicPoiPicker({
  city,
  isOpen,
  selectedPois,
  onClose,
  onSave,
}: CinematicPoiPickerProps) {
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<SelectablePoi[]>([]);
  const [nextAfterId, setNextAfterId] = useState<number | null>(null);
  const [localSelected, setLocalSelected] = useState<{ id: number; name: string }[]>([]);
  const [poiStatuses, setPoiStatuses] = useState<Record<number, { name: string, status: string }>>({});

  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  
  // Track failed request context for exact retry
  const [failedRequest, setFailedRequest] = useState<{
    q: string;
    reset: boolean;
    afterId: number;
  } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const [checkingSelection, setCheckingSelection] = useState(false);
  const [selectionError, setSelectionError] = useState(false);
  useEffect(() => {
    const ac = new AbortController();
    if (isOpen) {
      setLocalSelected([...selectedPois]);
      setPoiStatuses({});
      setSelectionError(false);
      setQ("");
      setCheckingSelection(selectedPois.length > 0);
      if (selectedPois.length) {
        checkPoiSelection(city, selectedPois.map(p => p.id), ac.signal).then(res => {
          if (ac.signal.aborted) return;
          const map: Record<number, { name: string; status: string }> = {};
          res.items.forEach(i => {
            if (i.status === "available") {
              map[i.place_id] = { name: i.place.name, status: "available" };
            } else {
              map[i.place_id] = { name: "", status: "unavailable" };
            }
          });
          setPoiStatuses(map);
        }).catch(() => { if (!ac.signal.aborted) setSelectionError(true); })
          .finally(() => { if (!ac.signal.aborted) setCheckingSelection(false); });
      }
    } else {
      setPlaces([]);
      setLocalSelected([]);
    }
    return () => { ac.abort(); abortControllerRef.current?.abort(); };
    // Open/city changes define a new selection editing session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, city]);

  // Debounce search
  useEffect(() => {
    if (!isOpen) return;
    const timer = setTimeout(() => {
      loadCatalog(true, q);
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, isOpen, city]);

  const loadCatalog = useCallback(
    async (reset: boolean, searchQuery: string, specificAfterId?: number) => {
      if (!city) return;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const ac = new AbortController();
      abortControllerRef.current = ac;

      if (reset) {
        setPlaces([]);
        setNextAfterId(null);
        setLoadingMore(false);
        setLoading(true);
        setError(null);
        setLoadMoreError(null);
      } else {
        setLoadingMore(true);
        setLoadMoreError(null);
      }
      setFailedRequest(null);

      const afterId = specificAfterId !== undefined ? specificAfterId : (reset ? 0 : nextAfterId || 0);

      try {
        const res = await fetchPoiCatalog(city, searchQuery, afterId, 20, ac.signal);
        
        if (ac.signal.aborted || abortControllerRef.current !== ac) return;
        // Remove duplicates when accumulating
        setPlaces((prev) => {
          if (reset) return res.places;
          const existingIds = new Set(prev.map(p => p.place_id));
          const newPlaces = res.places.filter(p => !existingIds.has(p.place_id));
          return [...prev, ...newPlaces];
        });
        setNextAfterId(res.next_after_id);
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        setFailedRequest({ q: searchQuery, reset, afterId });
        if (reset) {
          setError("地点加载失败，请重试");
        } else {
          setLoadMoreError("加载下一页失败，请重试");
        }
      } finally {
        if (abortControllerRef.current === ac) {
          if (reset) setLoading(false);
          else setLoadingMore(false);
        }
      }
    },
    [city, nextAfterId]
  );

  const handleRetry = () => {
    if (failedRequest) {
      loadCatalog(failedRequest.reset, failedRequest.q, failedRequest.afterId);
    } else {
      loadCatalog(places.length === 0, q);
    }
  };

  const togglePlace = (place: SelectablePoi) => {
    if (localSelected.some((p) => p.id === place.place_id)) {
      setLocalSelected((prev) => prev.filter((p) => p.id !== place.place_id));
    } else {
      if (localSelected.length >= 5) return;
      setLocalSelected((prev) => [...prev, { id: place.place_id, name: place.name }]);
    }
  };

  const handleSave = () => {
    if (checkingSelection || selectionError) return;
    const hasInvalid = localSelected.some(p => poiStatuses[p.id]?.status && poiStatuses[p.id].status !== "available");
      if (hasInvalid) {
        showToast("请先移除已失效的地点", "error");
        return;
      }
    const updated = localSelected.map(p => {
      const s = poiStatuses[p.id];
      if (s && s.status === "available" && s.name !== p.name) {
        return { id: p.id, name: s.name };
      }
      return p;
    });
    onSave(updated);
    onClose();
  };

  if (!isOpen) return null;

  const showEmptySearch = !loading && places.length === 0 && q.trim().length > 0 && !error;
  const showEmptyCity = !loading && places.length === 0 && q.trim().length === 0 && !error;

  return (
    <div className="cmp-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="poi-title">
      <div className="cmp-modal cmp-poi-modal" style={{ width: 440, maxWidth: "90vw", maxHeight: "85vh", display: 'flex', flexDirection: 'column' }}>
        <div className="cmp-modal-header" style={{ flexShrink: 0 }}>
          <h3 id="poi-title">选择必去地点 (最多5个)</h3>
          <button type="button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="cmp-poi-search" style={{ padding: "0 20px", flexShrink: 0 }}>
          <div className="cmp-search-input-row" style={{ marginTop: 0 }}>
            <Search size={16} style={{ opacity: 0.6 }} />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索必去地点..."
            />
            {q && (
              <button
                type="button"
                onClick={() => setQ("")}
                style={{ padding: 4, background: "none", border: "none", color: "inherit", opacity: 0.6, cursor: "pointer" }}
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        <div className="cmp-modal-body cmp-poi-list" style={{ flex: 1, overflowY: "auto", padding: "12px 20px" }}>
          {error && (
            <div className="cmp-poi-error" style={{ textAlign: "center", padding: 20 }}>
              <AlertCircle size={24} style={{ opacity: 0.6, margin: "0 auto 8px" }} />
              <div>{error}</div>
              <button
                type="button"
                className="cmp-text-button"
                style={{ marginTop: 8 }}
                onClick={() => loadCatalog(places.length === 0, q)}
              >
                重试
              </button>
            </div>
          )}

          {showEmptySearch && (
            <div style={{ textAlign: "center", padding: "30px 0", opacity: 0.6 }}>
              暂未收录<br/>换个名称试试，或从已收录地点中选择
            </div>
          )}

          {showEmptyCity && (
            <div style={{ textAlign: "center", padding: "40px 20px", color: "var(--cmp-text-muted)", fontSize: 13 }}>
              输入地点名称或类型进行搜索
            </div>
          )}

          {localSelected.length > 0 && (
            <div style={{ marginBottom: 16, paddingBottom: 16, borderBottom: "1px solid rgba(255,255,255,0.1)" }}>
              <div style={{ fontSize: 12, color: "var(--cmp-text-muted)", marginBottom: 8 }}>已选地点 ({localSelected.length}/5)</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {localSelected.map(p => {
                  const s = poiStatuses[p.id];
                  const isInvalid = s && s.status !== "available";
                  const nameChanged = s && s.status === "available" && s.name !== p.name;
                  return (
                    <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 4, background: "rgba(255,255,255,0.1)", padding: "4px 8px", borderRadius: 4, fontSize: 12, opacity: isInvalid ? 0.5 : 1 }}>
                      <span style={{ textDecoration: isInvalid ? 'line-through' : 'none' }}>{p.name}</span>
                      {isInvalid && <span style={{ color: "var(--cmp-error)" }}>(已失效)</span>}
                      {nameChanged && <span style={{ color: "var(--cmp-accent)" }}>(更名为: {s.name})</span>}
                      <button type="button" onClick={() => setLocalSelected(prev => prev.filter(x => x.id !== p.id))} style={{ opacity: 0.6, cursor: "pointer", background: "none", border: "none", padding: 0, color: "inherit" }}>
                        <X size={12} />
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {places.length > 0 && (
            <div style={{ fontSize: 12, color: "var(--cmp-text-muted)", marginBottom: 8 }}>搜索结果</div>
          )}

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {places.map((place) => {
              const isSelected = localSelected.some((p) => p.id === place.place_id);
              const disabled = !isSelected && localSelected.length >= 5;
              return (

                <label
                  key={place.place_id}
                  className="cmp-poi-item"
                  style={{ opacity: disabled ? 0.5 : 1, cursor: disabled ? "not-allowed" : "pointer" }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: "bold", color: "#f5efdf" }}>
                      {place.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--cmp-text-muted)" }}>
                      地点 #{place.place_id} · {place.place_type || "other"}
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    disabled={disabled}
                    onChange={() => togglePlace(place)}
                    style={{ width: 18, height: 18, accentColor: 'var(--cmp-accent)' }}
                  />
                </label>
              );
            })}
          </div>
          
          {nextAfterId !== null && !error && !loading && !loadMoreError && !loadingMore && (
            <button
              type="button"
              className="cmp-text-button"
              style={{ width: "100%", padding: 12, marginTop: 8 }}
              onClick={() => loadCatalog(false, q)}
            >
              加载更多
            </button>
          )}

          {loadingMore && (
            <div style={{ textAlign: "center", padding: 12, opacity: 0.6, fontSize: 12 }}>
              加载中...
            </div>
          )}

          {loadMoreError && (
            <div style={{ textAlign: "center", padding: 12, color: "var(--cmp-error)", fontSize: 12 }}>
              {loadMoreError}
              <button
                type="button"
                className="cmp-text-button"
                style={{ marginLeft: 8 }}
                onClick={handleRetry}
              >
                重试
              </button>
            </div>
          )}

          {loading && (
            <div style={{ textAlign: "center", padding: 20, opacity: 0.6 }}>
              搜索中...
            </div>
          )}
        </div>

        {selectionError && <p role="alert">已选地点校验失败，请关闭后重试</p>}
        <div className="cmp-modal-footer" style={{ flexShrink: 0 }}>
          <div style={{ fontSize: 12, opacity: 0.8 }}>已选 {localSelected.length}/5</div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button type="button" className="cmp-text-button" onClick={onClose}>取消</button>
            <button type="button" className="cmp-modal-save-btn" disabled={checkingSelection || selectionError} onClick={handleSave}>保存</button>
          </div>
        </div>
      </div>
    </div>
  );
}


