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
};

export function VoiceVisualizer({
  state,
  analyser,
  disabled,
  pipelineStage,
  partialTranscript,
  onPrimaryAction,
  onStop
}: VoiceVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>();
  const prefersReducedMotion = useReducedMotion();

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
      const pulse = 1 + (avg / 255) * 0.4;

      ctx.save();
      ctx.translate(w / 2, h / 2);
      ctx.scale(pulse, pulse);
      ctx.beginPath();
      ctx.arc(0, 0, radius - 12, 0, 2 * Math.PI);
      const g = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
      g.addColorStop(0, "rgba(79, 142, 247, 0.6)");
      g.addColorStop(0.6, "rgba(99, 102, 241, 0.3)");
      g.addColorStop(1, "rgba(79, 142, 247, 0)");
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
    ? "shadow-[0_0_80px_rgba(79,142,247,0.5),0_0_140px_rgba(99,102,241,0.2)]"
    : isProcessing
    ? "shadow-[0_0_60px_rgba(251,191,36,0.3),0_0_100px_rgba(251,191,36,0.1)]"
    : "shadow-[0_0_40px_rgba(79,142,247,0.15)] hover:shadow-[0_0_60px_rgba(79,142,247,0.3)]";

  const outerGlowColor = isRecording
    ? "from-blue-500/30 to-indigo-500/30"
    : isProcessing
    ? "from-amber-500/20 to-orange-500/20"
    : "from-blue-500/15 to-indigo-500/10";

  const buttonGradient = isRecording
    ? "from-[#4F8EF7] via-indigo-500 to-violet-600"
    : isProcessing
    ? "from-amber-500 via-yellow-500 to-orange-500"
    : "from-[#4F8EF7] via-indigo-500 to-blue-600";

  return (
    <motion.div
      className={cn("relative flex items-center justify-center rounded-full transition-shadow duration-700", orbGlow)}
      style={{ width: 280, height: 280 }}
    >
      <motion.div
        animate={prefersReducedMotion ? {
          scale: 1,
          rotate: 0,
        } : {
          scale: isRecording ? [1, 1.08, 1] : isProcessing ? [1, 1.04, 1] : [1, 1.03, 1],
          rotate: isProcessing ? 360 : 0,
        }}
        transition={{
          repeat: prefersReducedMotion ? 0 : Infinity,
          duration: isRecording ? 1.5 : isProcessing ? 5 : 4,
          ease: isProcessing ? "linear" : "easeInOut",
        }}
        className={cn("absolute inset-0 rounded-full opacity-60 blur-xl bg-gradient-to-r", outerGlowColor)}
      />

      <canvas
        ref={canvasRef}
        width={280}
        height={280}
        className="absolute inset-0 pointer-events-none rounded-full"
      />

      <button
        type="button"
        aria-label={isRecording ? "Stop recording" : "Start recording"}
        disabled={disabled || isConnecting || isProcessing}
        onClick={isRecording ? onStop : onPrimaryAction}
        className={cn(
          "z-10 flex h-28 w-28 items-center justify-center rounded-full text-white/90 transition-all duration-500",
          disabled
            ? "bg-[#4A4E69] cursor-not-allowed"
            : `bg-gradient-to-br ${buttonGradient}`,
          !disabled && !isProcessing && !isConnecting && "hover:scale-105",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--accent-blue)]"
        )}
      >
        {isRecording ? (
          <Square className="h-10 w-10 fill-current" />
        ) : isProcessing || isConnecting ? (
          <Loader2 className="h-10 w-10 animate-spin" />
        ) : (
          <Mic className="h-10 w-10" />
        )}
      </button>
    </motion.div>
  );
}
