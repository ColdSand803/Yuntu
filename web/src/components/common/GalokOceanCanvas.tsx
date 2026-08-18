import React, { useEffect, useRef } from 'react';

interface GalokOceanCanvasProps {
  theme?: 'auto' | 'day' | 'dusk' | 'night';
  interactive?: boolean;
}

export const GalokOceanCanvas: React.FC<GalokOceanCanvasProps> = ({
  theme = 'night',
  interactive = true,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl =
      canvas.getContext('webgl', { antialias: false, alpha: false, premultipliedAlpha: false }) ||
      (canvas.getContext('experimental-webgl') as WebGLRenderingContext | null);

    if (!gl) return;

    let animId: number;

    const VS = `
      attribute vec2 aPos;
      void main() {
        gl_Position = vec4(aPos, 0.0, 1.0);
      }
    `;

    const FS = `
      precision highp float;
      uniform vec2 uResolution;
      uniform float uTime;
      uniform vec2 uMouse;
      uniform float uNight;
      
      // 14 组正弦海浪 (kx, kz, amp, phase)
      vec4 getWave(int i) {
        if (i == 0) return vec4(-0.31, 0.25, 0.18, 0.4);
        if (i == 1) return vec4(0.52, 0.18, 0.14, 2.1);
        if (i == 2) return vec4(-0.74, -0.42, 0.09, 4.4);
        if (i == 3) return vec4(1.18, 0.56, 0.06, 1.7);
        if (i == 4) return vec4(-1.62, 0.92, 0.04, 5.3);
        if (i == 5) return vec4(2.1, -1.1, 0.03, 3.1);
        return vec4(0.1, 0.1, 0.02, 0.0);
      }

      void main() {
        vec2 uv = gl_FragCoord.xy / uResolution.xy;
        vec2 st = (gl_FragCoord.xy - uResolution.xy * 0.5) / min(uResolution.x, uResolution.y);

        // 海面高度计算
        float height = 0.0;
        vec2 waveGrad = vec2(0.0);
        
        for (int i = 0; i < 6; i++) {
          vec4 w = getWave(i);
          float k = length(w.xy);
          float phase = dot(w.xy, st * 12.0) - sqrt(9.81 * k) * uTime * 0.8 + w.w;
          height += w.z * cos(phase);
          waveGrad += w.xy * w.z * sin(phase);
        }

        // 鼠标交互水波涟漪
        float distToMouse = length(uv - uMouse);
        float ripple = sin(distToMouse * 40.0 - uTime * 6.0) * exp(-distToMouse * 6.0) * 0.05;
        height += ripple;

        // 海洋法线与菲涅尔反射 (Fresnel)
        vec3 normal = normalize(vec3(-waveGrad.x, 1.0, -waveGrad.y));
        vec3 viewDir = normalize(vec3(st.x, 0.8, 1.0));
        float fresnel = pow(1.0 - max(0.0, dot(normal, viewDir)), 3.0);

        // 海水颜色基调（白天 vs 深夜）
        vec3 deepColor = mix(vec3(0.04, 0.12, 0.22), vec3(0.02, 0.06, 0.14), uNight);
        vec3 shallowColor = mix(vec3(0.15, 0.45, 0.55), vec3(0.05, 0.22, 0.35), uNight);
        vec3 skyColor = mix(vec3(0.5, 0.75, 0.95), vec3(0.03, 0.08, 0.18), uNight);
        
        // 浪尖发光与水面高光
        float foam = smoothstep(0.12, 0.25, height);
        vec3 waterColor = mix(deepColor, shallowColor, height * 2.0 + 0.5);
        waterColor = mix(waterColor, vec3(0.8, 0.95, 1.0), foam * 0.3);
        
        vec3 finalColor = mix(waterColor, skyColor, fresnel * 0.6);
        
        // 增加微弱月光/晨光泛音
        finalColor += vec3(0.1, 0.35, 0.45) * pow(max(0.0, height), 2.0) * (1.0 - uNight);
        finalColor += vec3(0.15, 0.25, 0.35) * pow(max(0.0, height), 2.0) * uNight;

        gl_FragColor = vec4(finalColor, 1.0);
      }
    `;

    const createShader = (type: number, src: string) => {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, src);
      gl.compileShader(shader);
      return shader;
    };

    const vertShader = createShader(gl.VERTEX_SHADER, VS);
    const fragShader = createShader(gl.FRAGMENT_SHADER, FS);
    if (!vertShader || !fragShader) return;

    const prog = gl.createProgram();
    if (!prog) return;
    gl.attachShader(prog, vertShader);
    gl.attachShader(prog, fragShader);
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const posBuf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

    const aPos = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uRes = gl.getUniformLocation(prog, 'uResolution');
    const uTime = gl.getUniformLocation(prog, 'uTime');
    const uMouse = gl.getUniformLocation(prog, 'uMouse');
    const uNight = gl.getUniformLocation(prog, 'uNight');

    let mouseX = 0.5;
    let mouseY = 0.5;

    const handleMouseMove = (e: MouseEvent) => {
      if (!interactive) return;
      mouseX = e.clientX / window.innerWidth;
      mouseY = 1.0 - e.clientY / window.innerHeight;
    };

    if (interactive) {
      window.addEventListener('mousemove', handleMouseMove);
    }

    const handleResize = () => {
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };

    handleResize();
    window.addEventListener('resize', handleResize);

    const startTime = performance.now();
    const render = () => {
      const elapsed = (performance.now() - startTime) / 1000;
      const isNightVal = theme === 'night' ? 1.0 : theme === 'dusk' ? 0.6 : 0.0;

      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform1f(uTime, elapsed);
      gl.uniform2f(uMouse, mouseX, mouseY);
      gl.uniform1f(uNight, isNightVal);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      animId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', handleResize);
      if (interactive) {
        window.removeEventListener('mousemove', handleMouseMove);
      }
    };
  }, [theme, interactive]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0 h-full w-full"
    />
  );
};
