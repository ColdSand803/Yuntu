import React, { useEffect, useRef } from 'react';

interface YuntuTopoCanvasProps {
  interactive?: boolean;
}

export const YuntuTopoCanvas: React.FC<YuntuTopoCanvasProps> = ({ interactive = true }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = 0;
    let height = 0;

    let mouseX = 0;
    let mouseY = 0;

    const resize = () => {
      width = window.innerWidth;
      height = window.innerHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
      mouseX = width / 2;
      mouseY = height / 2;
    };

    resize();
    window.addEventListener('resize', resize);

    const handleMouseMove = (e: MouseEvent) => {
      if (!interactive) return;
      mouseX = e.clientX;
      mouseY = e.clientY;
    };

    if (interactive) {
      window.addEventListener('mousemove', handleMouseMove);
    }

    let time = 0;

    const render = () => {
      time += 0.006;
      ctx.clearRect(0, 0, width, height);

      // 云途青绿-沙丘色深邃背景
      const bgGrad = ctx.createRadialGradient(width / 2, height / 2, 100, width / 2, height / 2, width * 0.7);
      bgGrad.addColorStop(0, '#0f2926');
      bgGrad.addColorStop(0.7, '#091c1a');
      bgGrad.addColorStop(1, '#051110');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // 渲染 20 层重力引力变形等高线 (Gravitational Topo Lines)
      const numLines = 22;
      const centerX = width / 2;
      const centerY = height / 2;

      for (let i = 1; i <= numLines; i++) {
        const baseRadius = i * 28;
        ctx.beginPath();
        const steps = 120;

        for (let a = 0; a <= steps; a++) {
          const angle = (a / steps) * Math.PI * 2;
          
          // 原生等高线波动
          const r = baseRadius + Math.sin(angle * 4 + time * 2 + i * 0.3) * 12 + Math.cos(angle * 2 - time) * 8;

          // 算 3D 点在平面上的坐标
          let px = centerX + r * Math.cos(angle);
          let py = centerY + r * Math.sin(angle);

          // 鼠标重力引力扭曲 (Mouse Gravity Distortion)
          const dx = px - mouseX;
          const dy = py - mouseY;
          const dist = Math.hypot(dx, dy);
          if (dist < 180) {
            const factor = Math.sin((180 - dist) / 180 * Math.PI) * 22;
            px += (dx / dist) * factor;
            py += (dy / dist) * factor;
          }

          if (a === 0) {
            ctx.moveTo(px, py);
          } else {
            ctx.lineTo(px, py);
          }
        }

        ctx.closePath();
        ctx.strokeStyle = `rgba(45, 212, 191, ${0.08 + (i / numLines) * 0.18})`;
        ctx.lineWidth = i % 5 === 0 ? 1.5 : 0.8;
        ctx.stroke();
      }

      // 渲染罗盘风向标刻度圈
      ctx.save();
      ctx.translate(centerX, centerY);
      ctx.rotate(time * 0.05);

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(0, 0, 320, 0, Math.PI * 2);
      ctx.stroke();

      for (let deg = 0; deg < 360; deg += 30) {
        const rad = (deg * Math.PI) / 180;
        ctx.beginPath();
        ctx.moveTo(Math.cos(rad) * 310, Math.sin(rad) * 310);
        ctx.lineTo(Math.cos(rad) * 325, Math.sin(rad) * 325);
        ctx.stroke();
      }
      ctx.restore();

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
