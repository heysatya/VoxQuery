"use client";

import React, { useEffect, useRef } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Mic, Square, Loader2 } from "lucide-react";
import { cn } from "../../../lib/utils";
import type { RecordingState } from "../../../lib/types";

type VoiceVisualizerProps = {
  state: RecordingState;
  analyser: AnalyserNode | null;
  disabled: boolean;
  pipelineStage: string | null;
  partialTranscript: string;
  onPrimaryAction: () => void | Promise<void>;
  onStop: () => void;
  size?: "hero" | "compact";
};

export function VoiceVisualizer({
  state,
  analyser,
  disabled,
  pipelineStage,
  partialTranscript,
  onPrimaryAction,
  onStop,
  size = "hero"
}: VoiceVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>();
  const prefersReducedMotion = useReducedMotion();

  const outerDimensions = size === "hero" ? { w: 260, h: 260, btnSize: "h-24 w-24", iconSize: "h-9 w-9" } : { w: 140, h: 140, btnSize: "h-16 w-16", iconSize: "h-6 w-6" };

  useEffect(() => {
    if (prefersReducedMotion || !analyser || state !== "recording" || !canvasRef.current) {
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
      return;
    }

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const draw = () => {
      animationRef.current = requestAnimationFrame(draw);
      analyser.getByteFrequencyData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const w = canvas.width;
      const h = canvas.height;
      const radius = w / 2;

      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
      const avg = sum / dataArray.length;
      const pulse = 1 + (avg / 255) * 0.35;

      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(pulse, pulse);
      ctx.beginPath();
      ctx.arc(0, 0, radius - 10, 0, 2 * Math.PI);
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
      g.addColorStop(0, "rgba(56, 189, 248, 0.5)");
      g.addColorStop(0.6, "rgba(14, 165, 233, 0.2)");
      g.addColorStop(1, "rgba(56, 189, 248, 0)");
      ctx.fillStyle = g;
      ctx.fill();
      ctx.restore();
    };

    draw();
    return () => { if (animationRef.current) cancelAnimationFrame(animationRef.current); };
  }, [analyser, state, prefersReducedMotion]);

  const isRecording = state === "recording";
  const isConnecting = state === "connecting";
  const isProcessing = state === "processing" || pipelineStage !== null;

  const orbGlow = isRecording
    ? "shadow-[0_0_60px_rgba(56,189,248,0.4),0_0_100px_rgba(14,165,233,0.2)]"
    : isProcessing
    ? "shadow-[0_0_50px_rgba(245,158,11,0.3),0_0_80px_rgba(245,158,11,0.15)]"
    : "shadow-[0_0_30px_rgba(56,189,248,0.12)] hover:shadow-[0_0_50px_rgba(56,189,248,0.25)]";

  const outerGlowColor = isRecording
    ? "from-sky-500/25 to-cyan-500/25"
    : isProcessing
    ? "from-amber-500/20 to-orange-500/20"
    : "from-sky-500/15 to-indigo-500/10";

  const buttonGradient = isRecording
    ? "from-sky-500 via-cyan-600 to-emerald-500"
    : isProcessing
    ? "from-amber-500 via-yellow-500 to-orange-500"
    : "from-sky-500 via-cyan-500 to-indigo-600";

  return (
    <motion.div
      className={cn("relative flex items-center justify-center rounded-full transition-all duration-500", orbGlow)}
      style={{ width: outerDimensions.w, height: outerDimensions.h }}
    >
      <motion.div
        animate={prefersReducedMotion ? { scale: 1 } : {
          scale: isRecording ? [1, 1.06, 1] : isProcessing ? [1, 1.03, 1] : [1, 1.02, 1],
        }}
        transition={{
          repeat: prefersReducedMotion ? 0 : Infinity,
          duration: isRecording ? 1.5 : isProcessing ? 3 : 4,
          ease: "easeInOut",
        }}
        className={cn("absolute inset-0 rounded-full opacity-50 blur-lg bg-gradient-to-r", outerGlowColor)}
      />

      <canvas
        ref={canvasRef}
        width={outerDimensions.w}
        height={outerDimensions.h}
        className="absolute inset-0 pointer-events-none rounded-full"
      />

      <button
        type="button"
        aria-label={isRecording ? "Stop recording" : "Start recording"}
        disabled={disabled || isConnecting || isProcessing}
        onClick={isRecording ? onStop : onPrimaryAction}
        className={cn(
          "z-10 flex items-center justify-center rounded-full text-white transition-all duration-300 touch-target",
          outerDimensions.btnSize,
          disabled
            ? "bg-slate-800 text-slate-500 cursor-not-allowed border border-slate-700/50"
            : `bg-gradient-to-br ${buttonGradient} shadow-md`,
          !disabled && !isProcessing && !isConnecting && "hover:scale-105 active:scale-95",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-blue)]"
        )}
      >
        {isRecording ? (
          <Square className={cn(outerDimensions.iconSize, "fill-current")} />
        ) : isProcessing || isConnecting ? (
          <Loader2 className={cn(outerDimensions.iconSize, "animate-spin")} />
        ) : (
          <Mic className={outerDimensions.iconSize} />
        )}
      </button>
    </motion.div>
  );
}
