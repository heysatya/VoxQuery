"use client";

import React, { useState, useEffect, useRef } from "react";
import { Play, Pause, Volume2, VolumeX, Sparkles } from "lucide-react";

type ExecutiveAudioPlayerProps = {
  textToSpeak?: string;
  voiceUrl?: string;
  selectedVoice?: string;
  onVoiceChange?: (voice: string) => void;
};

export function ExecutiveAudioPlayer({
  textToSpeak = "Welcome back. Here is your morning briefing...",
  voiceUrl,
  selectedVoice = "aura-asteria-en",
  onVoiceChange,
}: ExecutiveAudioPlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1.0);
  const [progress, setProgress] = useState(0);
  const [isMuted, setIsMuted] = useState(false);
  const [hasAudioError, setHasAudioError] = useState(false);
  const synthRef = useRef<SpeechSynthesis | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const cleanSpeechText = React.useMemo(() => {
    return textToSpeak.replace(/[\*\_\`\#]/g, "").replace(/^\s*[\-\+]\s+/gm, "").trim();
  }, [textToSpeak]);

  useEffect(() => {
    if (typeof window !== "undefined") {
      synthRef.current = window.speechSynthesis;
    }
    return () => {
      if (synthRef.current) {
        synthRef.current.cancel();
      }
    };
  }, []);

  useEffect(() => {
    setHasAudioError(false);
    setProgress(0);
  }, [voiceUrl]);

  const speakWithSpeechSynthesis = () => {
    if (!synthRef.current) return;

    if (isPlaying) {
      synthRef.current.pause();
      setIsPlaying(false);
    } else {
      if (synthRef.current.paused) {
        synthRef.current.resume();
        setIsPlaying(true);
      } else {
        synthRef.current.cancel();
        const utterance = new SpeechSynthesisUtterance(cleanSpeechText);
        utterance.rate = playbackRate;
        utterance.volume = isMuted ? 0 : 1;

        // Auto-select smooth natural female voice for browser fallback
        const voices = synthRef.current.getVoices();
        const femaleVoice = voices.find(
          (v) =>
            v.name.includes("Asteria") ||
            v.name.includes("Google US English") ||
            v.name.includes("Samantha") ||
            v.name.includes("Zira") ||
            v.name.includes("Natural") ||
            v.name.toLowerCase().includes("female")
        );
        if (femaleVoice) {
          utterance.voice = femaleVoice;
        }

        utterance.onend = () => {
          setIsPlaying(false);
          setProgress(100);
        };
        utterance.onerror = () => {
          setIsPlaying(false);
        };
        utteranceRef.current = utterance;
        synthRef.current.speak(utterance);
        setIsPlaying(true);
        setProgress(0);
      }
    }
  };

  const handlePlayPause = () => {
    if (voiceUrl && !hasAudioError && audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
        setIsPlaying(false);
      } else {
        audioRef.current.playbackRate = playbackRate;
        audioRef.current.muted = isMuted;
        audioRef.current.play().then(() => setIsPlaying(true)).catch((err) => {
          console.warn("Audio element play failed, falling back to SpeechSynthesis", err);
          setHasAudioError(true);
          speakWithSpeechSynthesis();
        });
      }
      return;
    }
    speakWithSpeechSynthesis();
  };

  const toggleMute = () => {
    const nextMuted = !isMuted;
    setIsMuted(nextMuted);
    if (audioRef.current) {
      audioRef.current.muted = nextMuted;
    }
    if (synthRef.current && utteranceRef.current) {
      utteranceRef.current.volume = nextMuted ? 0 : 1;
    }
  };

  const handleSpeedChange = () => {
    const rates = [1.0, 1.25, 1.5, 2.0];
    const nextIdx = (rates.indexOf(playbackRate) + 1) % rates.length;
    const nextRate = rates[nextIdx];
    setPlaybackRate(nextRate);
    if (audioRef.current) {
      audioRef.current.playbackRate = nextRate;
    }
    if (synthRef.current && utteranceRef.current) {
      const wasPlaying = isPlaying;
      synthRef.current.cancel();
      const utterance = new SpeechSynthesisUtterance(cleanSpeechText);
      utterance.rate = nextRate;
      utterance.volume = isMuted ? 0 : 1;
      utterance.onend = () => {
        setIsPlaying(false);
        setProgress(100);
      };
      utteranceRef.current = utterance;
      if (wasPlaying) {
        synthRef.current.speak(utterance);
      }
    }
  };

  const handleTimeUpdate = () => {
    if (audioRef.current && audioRef.current.duration) {
      const currentProgress = (audioRef.current.currentTime / audioRef.current.duration) * 100;
      setProgress(currentProgress);
    }
  };

  return (
    <div className="w-full rounded-2xl bg-gradient-to-br from-indigo-950/40 to-slate-900/40 border border-indigo-500/20 shadow-2xl p-5 backdrop-blur-xl relative overflow-hidden">
      {voiceUrl && (
        <audio
          ref={audioRef}
          src={voiceUrl}
          onTimeUpdate={handleTimeUpdate}
          onEnded={() => {
            setIsPlaying(false);
            setProgress(100);
          }}
          onError={() => {
            setHasAudioError(true);
            setIsPlaying(false);
          }}
        />
      )}
      <div className="absolute top-0 right-0 p-3 opacity-20 pointer-events-none">
        <Sparkles className="w-20 h-20 text-indigo-400" />
      </div>

      <div className="flex flex-col md:flex-row items-center justify-between gap-5 relative z-10">
        {/* Info / Title */}
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={handlePlayPause}
            className="w-12 h-12 rounded-full bg-gradient-to-r from-indigo-500 to-purple-500 flex items-center justify-center text-white shadow-lg shadow-indigo-500/20 hover:scale-105 transition-transform"
            aria-label={isPlaying ? "Pause audio briefing" : "Play audio briefing"}
          >
            {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
          </button>
          <div>
            <h4 className="text-xs font-semibold text-indigo-300 uppercase tracking-widest font-mono">Executive Briefing Audio</h4>
            <p className="text-sm font-semibold text-[var(--text-primary)] mt-0.5">Morning Voice Podcast Summary</p>
          </div>
        </div>

        {/* Dynamic Waveform Visualizer */}
        <div className="flex-1 max-w-[200px] md:max-w-md h-8 flex items-center justify-center gap-1">
          {Array.from({ length: 24 }).map((_, idx) => {
            const h = isPlaying ? 10 + Math.sin(idx + progress) * 20 : 6;
            return (
              <span
                key={idx}
                style={{ height: `${Math.max(4, h)}px` }}
                className="w-1 rounded-full bg-indigo-500/40 transition-all duration-300"
              />
            );
          })}
        </div>

        {/* Controls */}
        <div className="flex items-center gap-3">
          <span className="px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-300 font-mono text-xs border border-indigo-500/20 flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${voiceUrl && !hasAudioError ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
            {voiceUrl && !hasAudioError ? "VoxQuery Voice (Asteria)" : "Native Speech Synthesis (Fallback)"}
          </span>

          {/* Playback speed */}
          <button
            type="button"
            onClick={handleSpeedChange}
            className="px-2.5 py-1 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 font-mono text-xs border border-indigo-500/20 transition-colors"
            aria-label={`Playback speed: ${playbackRate.toFixed(2)}x`}
          >
            {playbackRate.toFixed(2)}x
          </button>

          {/* Mute button */}
          <button
            type="button"
            onClick={toggleMute}
            className="p-2 rounded-lg bg-indigo-500/10 hover:bg-indigo-500/20 text-indigo-300 border border-indigo-500/20 transition-colors"
            aria-label={isMuted ? "Unmute audio" : "Mute audio"}
          >
            {isMuted ? <VolumeX className="w-4 h-4 text-rose-400" /> : <Volume2 className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Scrub Bar */}
      <div className="mt-4">
        <div className="w-full h-1 bg-indigo-500/15 rounded-full overflow-hidden">
          <div
            style={{ width: `${progress}%` }}
            className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 transition-all duration-300"
          />
        </div>
      </div>
    </div>
  );
}
