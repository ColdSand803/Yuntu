import React, { useEffect, useRef } from 'react';

interface YuntuCloudCanvasProps {
  interactive?: boolean;
}

export const YuntuCloudCanvas: React.FC<YuntuCloudCanvasProps> = ({ interactive = true }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = 0;
    let height = 0;

    // 粒子与星轨数据
    const particles: Array<{
      x: number;
      y: number;
      size: number;
      speedX: number;
      speedY: number;
      alpha: number;
      maxAlpha: number;
    }> = [];

    const mouseTrail: Array<{ x: number; y: number; alpha: number; radius: number }> = [];

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

    // 初始化云海微粒
    for (let i = 0; i < 70; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        size: Math.random() * 3 + 1,
        speedX: (Math.random() - 0.2) * 0.4,
        speedY: (Math.random() - 0.5) * 0.2,
        alpha: 0,
        maxAlpha: Math.random() * 0.6 + 0.2,
      });
    }

    const handleMouseMove = (e: MouseEvent) => {
      if (!interactive) return;
      mouseTrail.push({
        x: e.clientX,
        y: e.clientY,
        alpha: 0.8,
        radius: Math.random() * 25 + 15,
      });
      if (mouseTrail.length > 25) mouseTrail.shift();
    };

    if (interactive) {
      window.addEventListener('mousemove', handleMouseMove);
    }

    let time = 0;

    const render = () => {
      time += 0.008;
      ctx.clearRect(0, 0, width, height);

      // 1. 云途蓝紫-夜空星云背景
      const bgGrad = ctx.createLinearGradient(0, 0, width, height);
      bgGrad.addColorStop(0, '#091326');
      bgGrad.addColorStop(0.5, '#0d1f3d');
      bgGrad.addColorStop(1, '#070e1c');
      ctx.fillStyle = bgGrad;
      ctx.fillRect(0, 0, width, height);

      // 2. 渲染云途三维流云（三层柔和云雾扩散）
      for (let i = 0; i < 3; i++) {
        const cloudX = ((time * (15 + i * 10)) % (width + 400)) - 200;
        const cloudY = height * (0.3 + i * 0.2) + Math.sin(time + i) * 30;
        const cloudGrad = ctx.createRadialGradient(
          cloudX,
          cloudY,
          50,
          cloudX,
          cloudY,
          300 + i * 100
        );
        cloudGrad.addColorStop(0, `rgba(45, 212, 191, ${0.12 - i * 0.03})`);
        cloudGrad.addColorStop(0.5, `rgba(15, 118, 110, ${0.08 - i * 0.02})`);
        cloudGrad.addColorStop(1, 'rgba(0, 0, 0, 0)');

        ctx.fillStyle = cloudGrad;
        ctx.beginPath();
        ctx.arc(cloudX, cloudY, 400 + i * 100, 0, Math.PI * 2);
        ctx.fill();
      }

      // 3. 渲染鼠标云雾穿透轨迹 (Cloud Turbulence Trail)
      mouseTrail.forEach((p, idx) => {
        p.alpha *= 0.94;
        const trailGrad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius);
        trailGrad.addColorStop(0, `rgba(45, 212, 191, ${p.alpha * 0.3})`);
        trailGrad.addColorStop(1, 'rgba(45, 212, 191, 0)');

        ctx.fillStyle = trailGrad;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius * 2, 0, Math.PI * 2);
        ctx.fill();

        if (idx > 0) {
          const prev = mouseTrail[idx - 1];
          ctx.beginPath();
          ctx.moveTo(prev.x, prev.y);
          ctx.lineTo(p.x, p.y);
          ctx.strokeStyle = `rgba(45, 212, 191, ${p.alpha * 0.2})`;
          ctx.lineWidth = p.radius * 0.8;
          ctx.lineCap = 'round';
          ctx.stroke();
        }
      });

      // 4. 渲染漂浮星微粒 (Star Trails)
      particles.forEach((p) => {
        p.x += p.speedX;
        p.y += p.speedY;

        if (p.x > width) p.x = 0;
        if (p.x < 0) p.x = width;
        if (p.y > height) p.y = 0;
        if (p.y < 0) p.y = height;

        p.alpha += (p.maxAlpha - p.alpha) * 0.05;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${p.alpha})`;
        ctx.shadowColor = '#2dd4bf';
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;
      });

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
