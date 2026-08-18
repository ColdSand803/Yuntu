import React, { useEffect, useRef } from 'react';

interface MigratoryBirdsCanvasProps {
  interactive?: boolean;
  onPanUpdate?: (panOffset: number) => void;
  showSkyGradient?: boolean;
}

interface Boid {
  x: number;
  y: number;
  speed: number;
  angle: number;
  wingPhase: number;
  wingSpeed: number;
  size: number;
  floatOffset: number;
}

export const MigratoryBirdsCanvas: React.FC<MigratoryBirdsCanvasProps> = ({
  interactive = true,
  onPanUpdate,
  showSkyGradient = false,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const onPanUpdateRef = useRef(onPanUpdate);

  useEffect(() => {
    onPanUpdateRef.current = onPanUpdate;
  }, [onPanUpdate]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let width = window.innerWidth || 1200;
    let height = window.innerHeight || 800;

    let mouseX = width * 0.5;
    let mouseY = height * 0.35;
    let hasMouse = false;
    let cameraX = 0;

    // 45 只自然候鸟群体
    const numBoids = 45;
    const boids: Boid[] = [];

    for (let i = 0; i < numBoids; i++) {
      boids.push({
        x: Math.random() * width,
        y: Math.random() * height,
        speed: 1.2 + Math.random() * 0.6, // 极度优雅沉稳的巡航速度
        angle: -0.05 + (Math.random() - 0.5) * 0.2, // 默认顺畅向前
        wingPhase: Math.random() * Math.PI * 2,
        wingSpeed: 0.04 + Math.random() * 0.02, // 舒缓温和的扇羽频率
        size: 7 + Math.random() * 5,
        floatOffset: Math.random() * Math.PI * 2,
      });
    }

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
      hasMouse = true;
      mouseX = e.clientX;
      mouseY = e.clientY;
    };

    if (interactive) {
      window.addEventListener('mousemove', handleMouseMove);
    }

    let time = 0;

    const normalizeAngle = (diff: number) => {
      while (diff > Math.PI) diff -= Math.PI * 2;
      while (diff < -Math.PI) diff += Math.PI * 2;
      return diff;
    };

    // 第一版优雅自然的候鸟剪影
    const drawBird = (
      x: number,
      y: number,
      angle: number,
      wingAngle: number,
      size: number,
      alpha: number
    ) => {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);

      ctx.fillStyle = `rgba(25, 20, 15, ${alpha})`;
      ctx.strokeStyle = `rgba(25, 20, 15, ${alpha})`;
      ctx.lineWidth = 1.2;

      // 鸟头部
      ctx.beginPath();
      ctx.arc(size * 0.4, 0, size * 0.15, 0, Math.PI * 2);
      ctx.fill();

      // 自然翼角扇动
      const wingY = Math.sin(wingAngle) * size * 0.65;
      ctx.beginPath();
      ctx.moveTo(size * 0.3, 0);
      ctx.quadraticCurveTo(0, -size * 0.8 + wingY, -size * 0.6, -size * 1.3 + wingY * 1.4);
      ctx.quadraticCurveTo(-size * 0.2, -size * 0.3, 0, 0);
      ctx.quadraticCurveTo(-size * 0.2, size * 0.3, -size * 0.6, size * 1.3 - wingY * 1.4);
      ctx.quadraticCurveTo(0, size * 0.8 - wingY, size * 0.3, 0);
      ctx.fill();

      ctx.restore();
    };

    const render = () => {
      time += 0.016;
      ctx.clearRect(0, 0, width, height);

      if (showSkyGradient) {
        const skyGrad = ctx.createLinearGradient(0, 0, 0, height);
        skyGrad.addColorStop(0, '#f2ece1');
        skyGrad.addColorStop(0.45, '#f5efdf');
        skyGrad.addColorStop(0.8, '#e6ded0');
        skyGrad.addColorStop(1, '#d8cfbf');
        ctx.fillStyle = skyGrad;
        ctx.fillRect(0, 0, width, height);
      }

      let totalVX = 0;
      // 极度平滑的角惯性限制 (0.008 rad/frame，约 0.45度/帧，实现极度丝滑优雅的翱翔)
      const maxTurnRate = 0.008;

      boids.forEach((boid, idx) => {
        let targetAngle = -0.05;

        if (hasMouse) {
          const dx = mouseX - boid.x;
          const dy = mouseY - boid.y;
          const dist = Math.hypot(dx, dy);

          if (dist > 160) {
            targetAngle = Math.atan2(dy, dx);
          }
        }

        // Boid 群体凝聚与排斥
        for (let j = 0; j < boids.length; j++) {
          if (idx === j) continue;
          const other = boids[j];
          const d = Math.hypot(other.x - boid.x, other.y - boid.y);

          if (d < 45) {
            const avoidAngle = Math.atan2(boid.y - other.y, boid.x - other.x);
            targetAngle = targetAngle * 0.85 + avoidAngle * 0.15;
          }
        }

        const angleDiff = normalizeAngle(targetAngle - boid.angle);
        const turn = Math.max(-maxTurnRate, Math.min(maxTurnRate, angleDiff));
        boid.angle += turn;

        // 微小的自然空气浮力正弦摆动 (Air Current Soaring Oscillation)
        const floatY = Math.sin(time * 1.5 + boid.floatOffset) * 0.2;

        const vx = Math.cos(boid.angle) * boid.speed;
        const vy = Math.sin(boid.angle) * boid.speed + floatY;

        boid.x += vx;
        boid.y += vy;

        // 循环穿入
        if (boid.x > width + 60) boid.x = -60;
        if (boid.x < -60) boid.x = width + 60;
        if (boid.y > height + 60) boid.y = -60;
        if (boid.y < -60) boid.y = height + 60;

        boid.wingPhase += boid.wingSpeed;

        totalVX += vx;

        const alpha = Math.min(0.9, 0.35 + (boid.size / 12) * 0.55);
        drawBird(boid.x, boid.y, boid.angle, boid.wingPhase, boid.size, alpha);
      });

      // 画轴平移
      const avgVX = totalVX / numBoids;
      cameraX -= avgVX * 0.3;
      if (onPanUpdateRef.current) {
        onPanUpdateRef.current(cameraX);
      }

      animId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', resize);
      if (interactive) window.removeEventListener('mousemove', handleMouseMove);
    };
  }, [interactive, showSkyGradient]);

  return <canvas ref={canvasRef} className="pointer-events-none fixed inset-0 z-[1] h-full w-full" />;
};
