import React, { useEffect, useRef } from 'react';

interface YuntuInkTrailsProps {
  interactive?: boolean;
}

export const YuntuInkTrails: React.FC<YuntuInkTrailsProps> = ({ interactive = true }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = 0;
    let height = 0;

    const points: Array<{ x: number; y: number; alpha: number; radius: number }> = [];

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    };

    resize();
    window.addEventListener('resize', resize);

    const handleMouseMove = (e: MouseEvent) => {
      if (!interactive) return;
      points.push({
        x: e.clientX,
        y: e.clientY,
        alpha: 0.6,
        radius: Math.random() * 4 + 2,
      });
      if (points.length > 40) points.shift();
    };

    if (interactive) {
      window.addEventListener('mousemove', handleMouseMove);
    }

    let time = 0;

    const render = () => {
      time += 0.01;
      ctx.clearRect(0, 0, width, height);

      // 1. 动态网格点
      const gridSize = 60;
      ctx.fillStyle = 'rgba(120, 110, 100, 0.15)';
      for (let x = 0; x < width; x += gridSize) {
        for (let y = 0; y < height; y += gridSize) {
          const wave = Math.sin(x * 0.01 + y * 0.01 + time) * 1.5;
          ctx.beginPath();
          ctx.arc(x + 30, y + 30, 1 + wave * 0.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // 2. 墨迹尾迹描边
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        p.alpha *= 0.94;

        if (i > 0) {
          const prev = points[i - 1];
          ctx.beginPath();
          ctx.moveTo(prev.x, prev.y);
          ctx.lineTo(p.x, p.y);
          ctx.strokeStyle = `rgba(40, 35, 30, ${p.alpha * 0.4})`;
          ctx.lineWidth = p.radius;
          ctx.lineCap = 'round';
          ctx.stroke();
        }
      }

      animId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', resize);
      if (interactive) window.removeEventListener('mousemove', handleMouseMove);
    };
  }, [interactive]);

  return <canvas ref={canvasRef} className="pointer-events-none fixed inset-0 z-0 h-full w-full" />;
};
