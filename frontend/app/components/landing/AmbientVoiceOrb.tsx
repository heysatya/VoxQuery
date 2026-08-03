"use client";

import React, { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";

type AmbientVoiceOrbProps = {
  className?: string;
};

/**
 * A synthetic "listening" waveform orb for the public landing page.
 * Visually related to the in-app VoiceVisualizer (same glow language, same
 * accent colors) but driven by a synthetic amplitude signal instead of a
 * real microphone AnalyserNode — this page never requests mic access.
 */
export function AmbientVoiceOrb({ className = "" }: AmbientVoiceOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<number>();
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bars = 48;
    let cssSize = 0;
    const dpr = typeof window !== "undefined" ? Math.min(window.devicePixelRatio || 1, 2) : 1;

    // Match the canvas's backing resolution to its actual displayed size
    // (times devicePixelRatio) so the orb stays crisp at any container size
    // instead of being stretched from a fixed intrinsic resolution.
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      cssSize = Math.max(rect.width, rect.height);
      if (cssSize === 0) return;
      canvas.width = cssSize * dpr;
      canvas.height = cssSize * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const resizeObserver = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    resizeObserver?.observe(canvas);

    if (prefersReducedMotion) {
      // Static, calm rendering: no rAF loop.
      drawFrame(ctx, cssSize, bars, staticAmplitudes(bars));
      return () => resizeObserver?.disconnect();
    }

    const start = performance.now();
    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const amplitudes = syntheticAmplitudes(bars, t);
      drawFrame(ctx, cssSize, bars, amplitudes);
      frameRef.current = requestAnimationFrame(draw);
    };
    frameRef.current = requestAnimationFrame(draw);

    return () => {
      if (frameRef.current) cancelAnimationFrame(frameRef.current);
      resizeObserver?.disconnect();
    };
  }, [prefersReducedMotion]);

  return <canvas ref={canvasRef} aria-hidden="true" className={className} />;
}

function staticAmplitudes(bars: number): number[] {
  return new Array(bars).fill(0).map((_, i) => 0.25 + 0.15 * Math.sin(i));
}

function syntheticAmplitudes(bars: number, t: number): number[] {
  const amplitudes: number[] = [];
  for (let i = 0; i < bars; i++) {
    const angle = (i / bars) * Math.PI * 2;
    // Layer a few slow sine waves at different phases/frequencies so the
    // orb breathes organically rather than pulsing uniformly, evoking a
    // waveform actively listening to speech.
    const wave =
      Math.sin(angle * 3 + t * 1.6) * 0.4 +
      Math.sin(angle * 5 - t * 0.9) * 0.3 +
      Math.sin(angle * 1.5 + t * 0.5) * 0.3;
    amplitudes.push(0.45 + wave * 0.28);
  }
  return amplitudes;
}

function drawFrame(ctx: CanvasRenderingContext2D, size: number, bars: number, amplitudes: number[]) {
  ctx.clearRect(0, 0, size, size);
  const cx = size / 2;
  const cy = size / 2;
  const innerRadius = size * 0.22;
  const maxBarLength = size * 0.24;

  // Core glow
  const coreGradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, innerRadius * 1.6);
  coreGradient.addColorStop(0, "rgba(56, 189, 248, 0.35)");
  coreGradient.addColorStop(0.55, "rgba(16, 185, 129, 0.12)");
  coreGradient.addColorStop(1, "rgba(56, 189, 248, 0)");
  ctx.fillStyle = coreGradient;
  ctx.beginPath();
  ctx.arc(cx, cy, innerRadius * 1.6, 0, Math.PI * 2);
  ctx.fill();

  // Radial bars, like a circular spectrum analyzer
  for (let i = 0; i < bars; i++) {
    const angle = (i / bars) * Math.PI * 2 - Math.PI / 2;
    const amp = Math.max(0.08, Math.min(1, amplitudes[i]));
    const barLength = maxBarLength * amp;
    const x1 = cx + Math.cos(angle) * innerRadius;
    const y1 = cy + Math.sin(angle) * innerRadius;
    const x2 = cx + Math.cos(angle) * (innerRadius + barLength);
    const y2 = cy + Math.sin(angle) * (innerRadius + barLength);

    const gradient = ctx.createLinearGradient(x1, y1, x2, y2);
    gradient.addColorStop(0, "rgba(56, 189, 248, 0.85)");
    gradient.addColorStop(1, "rgba(16, 185, 129, 0.15)");

    ctx.strokeStyle = gradient;
    ctx.lineWidth = size * 0.006;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  // Inner ring
  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2);
  ctx.stroke();
}
