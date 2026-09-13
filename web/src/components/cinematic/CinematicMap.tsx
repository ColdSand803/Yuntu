import React, { type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import type { MapCityPoint } from "@/constants/chinaGeo";
import {
  CHINA_OUTLINE_PATH,
  CITY_LABEL_OFFSETS,
} from "@/constants/chinaGeo";

interface CinematicMapProps {
  cities: MapCityPoint[];
  selectedCity: MapCityPoint | null;
  onSelectCity: (city: MapCityPoint) => void;
  onMapClick?: (clientX: number, clientY: number) => void;
  cameraRef: React.RefObject<SVGGElement>;
  svgRef: React.RefObject<SVGSVGElement>;
  view: { x: number; y: number; zoom: number };
  onUpdateView: (next: { x: number; y: number; zoom: number }) => void;
  dragging: boolean;
  setDragging: (dragging: boolean) => void;
  pointersRef: React.MutableRefObject<Map<number, { x: number; y: number }>>;
  gestureRef: React.MutableRefObject<{
    moved: boolean;
    x: number;
    y: number;
    gap: number;
  }>;
  immersed: boolean;
  moving: boolean;
}

const clamp = (val: number, min: number, max: number) =>
  Math.min(max, Math.max(min, val));

export function CinematicMap({
  cities,
  selectedCity,
  onSelectCity,
  onMapClick,
  cameraRef,
  svgRef,
  view,
  onUpdateView,
  dragging,
  setDragging,
  pointersRef,
  gestureRef,
  immersed,
  moving,
}: CinematicMapProps) {
  const latestView = React.useRef(view);
  React.useEffect(() => {
    latestView.current = view;
  }, [view]);

  function getSvgPoint(clientX: number, clientY: number) {
    const matrix = typeof svgRef.current?.getScreenCTM === 'function' ? svgRef.current?.getScreenCTM() : null;
    return matrix
      ? new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse())
      : new DOMPoint(450, 350);
  }

  function handlePointerDown(e: ReactPointerEvent<SVGSVGElement>) {
    if (immersed || moving || (e.pointerType === "mouse" && e.button !== 0))
      return;
    const pt = getSvgPoint(e.clientX, e.clientY);
    if (!pointersRef.current.size) {
      gestureRef.current = {
        moved: false,
        x: e.clientX,
        y: e.clientY,
        gap: 0,
      };
    }
    pointersRef.current.set(e.pointerId, pt);
    if (pointersRef.current.size > 1) {
      const [a, b] = [...pointersRef.current.values()];
      gestureRef.current.gap = Math.hypot(a.x - b.x, a.y - b.y);
      gestureRef.current.moved = true;
    }
  }

  function handlePointerMove(e: ReactPointerEvent<SVGSVGElement>) {
    const prev = pointersRef.current.get(e.pointerId);
    if (!prev) return;
    const pt = getSvgPoint(e.clientX, e.clientY);
    pointersRef.current.set(e.pointerId, pt);

    if (
      Math.hypot(
        e.clientX - gestureRef.current.x,
        e.clientY - gestureRef.current.y,
      ) > 6
    ) {
      gestureRef.current.moved = true;
    }

    if (!gestureRef.current.moved) return;

    if (!e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    setDragging(true);

    const currView = latestView.current;

    if (pointersRef.current.size > 1) {
      const [a, b] = [...pointersRef.current.values()];
      const gap = Math.hypot(a.x - b.x, a.y - b.y);
      if (gestureRef.current.gap > 0) {
        const nextZoom = clamp((currView.zoom * gap) / gestureRef.current.gap, 0.85, 3.5);
        const anchor = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const ratio = nextZoom / currView.zoom;
        const nextView = {
          zoom: nextZoom,
          x: clamp(anchor.x - (anchor.x - currView.x) * ratio, -1600, 500),
          y: clamp(anchor.y - (anchor.y - currView.y) * ratio, -1300, 450),
        };
        latestView.current = nextView;
        onUpdateView(nextView);
      }
      gestureRef.current.gap = gap;
    } else {
      const nextView = {
        ...currView,
        x: clamp(currView.x + pt.x - prev.x, -1600, 500),
        y: clamp(currView.y + pt.y - prev.y, -1300, 450),
      };
      latestView.current = nextView;
      onUpdateView(nextView);
    }
  }

  function handlePointerUp(e: ReactPointerEvent<SVGSVGElement>) {
    pointersRef.current.delete(e.pointerId);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    if (!pointersRef.current.size) {
      setDragging(false);
    }
  }

  return (
    <div
      className="cmp-atlas"
      aria-hidden={immersed}
      style={{ pointerEvents: immersed || moving ? "none" : undefined }}
    >
      <svg
        ref={svgRef}
        viewBox="0 0 900 700"
        className={dragging ? "is-dragging" : ""}
        aria-label="探索目的地地图"
        onClick={(e) => {
          if (!gestureRef.current.moved && !immersed && !moving) {
            const target = e.target as SVGElement;
            if (
              target === svgRef.current ||
              target.classList?.contains("cmp-land") ||
              target.classList?.contains("cmp-islands")
            ) {
              onMapClick?.(e.clientX, e.clientY);
            }
          }
        }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={(e) => {
          gestureRef.current.moved = true;
          handlePointerUp(e);
        }}
        onPointerLeave={(e) => {
          if (!e.currentTarget.hasPointerCapture(e.pointerId)) {
            handlePointerUp(e);
          }
        }}
      >
        <defs>
          <clipPath id="cmp-mainland-clip">
            <rect width="900" height="700" />
          </clipPath>
        </defs>

        <g transform={`translate(${view.x} ${view.y}) scale(${view.zoom})`}>
          <g ref={cameraRef}>
            <path
              d={CHINA_OUTLINE_PATH}
              className="cmp-land"
              clipPath="url(#cmp-mainland-clip)"
              vectorEffect="non-scaling-stroke"
            />
            {cities.map((city, index) => {
              const active = selectedCity?.name === city.name;
              const offset = CITY_LABEL_OFFSETS[city.name] ?? {
                dx: 10,
                dy: 0,
                align: "start" as const,
              };
              const labelVisible =
                active ||
                view.zoom > 1.45 ||
                !["苏州", "南京", "长沙", "桂林"].includes(city.name);

              return (
                <g
                  key={city.name}
                  transform={`translate(${city.x} ${city.y})`}
                  className={`cmp-city ${active ? "is-selected" : ""}`}
                  role="button"
                  aria-label={`选择目的地城市 ${city.name}`}
                  aria-pressed={active}
                  tabIndex={immersed || moving ? -1 : 0}
                  onClick={() => {
                    if (!gestureRef.current.moved) onSelectCity(city);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelectCity(city);
                    }
                  }}
                >
                  <g 
                    className="cmp-city-content"
                    style={{ "--zoom-inv": 1 / view.zoom } as CSSProperties}
                  >
                    {active && (
                      <circle
                        className="cmp-city-halo"
                        r="18"
                        style={
                          {
                            animationDelay: `${index * -0.5}s`,
                          } as CSSProperties
                        }
                      />
                    )}
                    {active && <circle className="cmp-city-ring" r="15" />}
                    <circle className="cmp-city-dot" r={active ? 5 : 3} />
                    <circle className="cmp-city-focus-ring" r="20" />
                    {labelVisible && (
                      <text
                        x={offset.dx}
                        y={offset.dy}
                        textAnchor={offset.align}
                        dominantBaseline="middle"
                      >
                        {city.name}
                      </text>
                    )}
                  </g>
                </g>
              );
            })}
        <svg
          x="796"
          y="554"
          width="58"
          height="90"
          viewBox="480 690 250 270"
          className="cmp-islands"
          aria-label="南海诸岛"
        >
          <path
            d={CHINA_OUTLINE_PATH}
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          />
        </svg>
        <text
          x="825"
          y="658"
          textAnchor="middle"
          className="cmp-islands-label"
        >
          南海诸岛
        </text>
          </g>
        </g>
      </svg>
    </div>
  );
}
