"use client";
import { useEffect, useRef } from "react";

/** Slowly drifting bathymetric contour lines (pure canvas, ~60 lines, pauses when reduced motion). */
export default function HeroCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current!;
    const g = c.getContext("2d")!;
    let raf = 0, t = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const resize = () => { c.width = c.clientWidth * devicePixelRatio; c.height = c.clientHeight * devicePixelRatio; };
    resize();
    window.addEventListener("resize", resize);
    const draw = () => {
      const w = c.width, h = c.height;
      g.clearRect(0, 0, w, h);
      const n = 46;
      for (let i = 0; i < n; i++) {
        const base = (i / n) * h * 1.15 - h * 0.05;
        const depth = i / n;
        g.beginPath();
        for (let x = 0; x <= w; x += 8 * devicePixelRatio) {
          const u = x / w;
          const y = base
            + Math.sin(u * 5.2 + i * 0.35 + t * 0.35) * 18 * devicePixelRatio * (0.4 + depth)
            + Math.sin(u * 13 - i * 0.2 + t * 0.21) * 6 * devicePixelRatio
            + Math.exp(-(((u - 0.68) / 0.13) ** 2)) * -60 * devicePixelRatio * Math.sin(i * 0.25 + 1.2);
          if (x === 0) g.moveTo(x, y); else g.lineTo(x, y);
        }
        const a = 0.05 + 0.2 * (1 - Math.abs(depth - 0.55) * 1.6);
        g.strokeStyle = i % 5 === 0 ? `rgba(67,211,198,${a * 1.6})` : `rgba(57,135,229,${a})`;
        g.lineWidth = (i % 5 === 0 ? 1.2 : 0.7) * devicePixelRatio;
        g.stroke();
      }
      t += 0.012;
      if (!reduce) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", resize); };
  }, []);
  return <canvas ref={ref} className="absolute inset-0 h-full w-full" aria-hidden />;
}
