import { useEffect, useRef } from "react";

type Particle = {
  x: number;
  y: number;
  nx: number;
  ny: number;
  mask: number;
  halo: number;
};

function smooth(value: number) {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
}

export function AuthParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const logo = new Image();
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let width = 0;
    let height = 0;
    let elapsed = 0;
    let lastFrame = 0;
    let frame = 0;
    let particles: Particle[] = [];
    let background: CanvasGradient | null = null;
    let color = "";

    function draw() {
      if (!context || !background || !width || !height) return;

      const time = reducedMotion.matches ? 6 : elapsed;
      context.globalAlpha = 1;
      context.fillStyle = background;
      context.fillRect(0, 0, width, height);
      context.globalAlpha = 0.72;
      context.fillStyle = color;
      context.beginPath();
      for (const { x, y, nx, ny, mask, halo } of particles) {
        const wave =
          Math.sin(nx * 8 + ny * 4 - time * 0.45) +
          0.65 * Math.sin(ny * 9 - nx * 5 + time * 0.65) +
          0.4 * Math.cos((nx - ny) * 12 - time * 0.5);
        const baseRadius = 0.1 + 1.6 * smooth((wave + 1.6) / 3.2);
        const passage = smooth(
          (Math.cos((nx - 0.5) * 2 + ny - 0.5 - time * 0.45) + 0.2) / 0.95,
        );
        const amount = passage * 0.85;
        const radius =
          baseRadius * (1 - amount * halo) +
          amount * (0.15 * halo + 1.5 * mask);
        if (radius <= 0.13) continue;
        context.moveTo(x + radius, y);
        context.arc(x, y, radius, 0, Math.PI * 2);
      }
      context.fill();
    }

    function tick(now: number) {
      if (now - lastFrame >= 1000 / 30) {
        elapsed += Math.min((now - lastFrame) / 1000, 0.07);
        lastFrame = now;
        draw();
      }
      frame = requestAnimationFrame(tick);
    }

    function sync() {
      cancelAnimationFrame(frame);
      if (!canvas || !context || !width || !height) return;

      const style = getComputedStyle(canvas);
      color = style.getPropertyValue("--auth-particle-dots").trim();
      background = context.createRadialGradient(
        width * 0.47,
        height * 0.44,
        0,
        width * 0.47,
        height * 0.44,
        width * 0.82,
      );
      background.addColorStop(
        0,
        style.getPropertyValue("--auth-particle-center").trim(),
      );
      background.addColorStop(
        0.6,
        style.getPropertyValue("--auth-particle-base").trim(),
      );
      background.addColorStop(
        1,
        style.getPropertyValue("--auth-particle-edge").trim(),
      );
      draw();
      if (!reducedMotion.matches && !document.hidden) {
        lastFrame = performance.now();
        frame = requestAnimationFrame(tick);
      }
    }

    function resize() {
      if (!canvas || !context) return;

      width = canvas.clientWidth;
      height = canvas.clientHeight;
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * scale);
      canvas.height = Math.round(height * scale);
      context.setTransform(scale, 0, 0, scale, 0, 0);
      particles = [];
      if (!width || !height) {
        sync();
        return;
      }

      const sampler = document.createElement("canvas");
      sampler.width = width;
      sampler.height = height;
      const sampleContext = sampler.getContext("2d", {
        willReadFrequently: true,
      });
      if (!sampleContext) return;

      const logoWidth = width * 0.8;
      const logoHeight = (logoWidth * logo.naturalHeight) / logo.naturalWidth;
      if (logo.complete && logo.naturalWidth) {
        sampleContext.filter = "blur(8px)";
        sampleContext.drawImage(
          logo,
          (width - logoWidth) / 2,
          (height - logoHeight) / 2,
          logoWidth,
          logoHeight,
        );
      }
      const data = sampleContext.getImageData(0, 0, width, height).data;
      sampleContext.clearRect(0, 0, width, height);
      if (logo.complete && logo.naturalWidth) {
        sampleContext.filter = "blur(32px)";
        sampleContext.drawImage(
          logo,
          (width - logoWidth) / 2,
          (height - logoHeight) / 2,
          logoWidth,
          logoHeight,
        );
      }
      const haloData = sampleContext.getImageData(0, 0, width, height).data;
      const spacing = width < 400 ? 3.5 : 4.5;
      for (let y = 2; y < height; y += spacing) {
        for (let x = 2; x < width; x += spacing) {
          const index = (Math.floor(y) * width + Math.floor(x)) * 4 + 3;
          const mask = data[index] / 255;
          const halo = Math.max(
            mask,
            Math.min(1, (haloData[index] / 255) * 2.2),
          );
          particles.push({ x, y, nx: x / width, ny: y / height, mask, halo });
        }
      }
      sync();
    }

    const resizeObserver = new ResizeObserver(resize);
    const themeObserver = new MutationObserver(sync);
    resizeObserver.observe(canvas);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    reducedMotion.addEventListener("change", sync);
    document.addEventListener("visibilitychange", sync);
    logo.addEventListener("load", resize);
    logo.src = "/logo.svg";
    resize();

    return () => {
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      themeObserver.disconnect();
      reducedMotion.removeEventListener("change", sync);
      document.removeEventListener("visibilitychange", sync);
      logo.removeEventListener("load", resize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      data-slot="auth-particle-background"
      className="pointer-events-none absolute inset-0 size-full bg-(--auth-particle-base)"
    />
  );
}
