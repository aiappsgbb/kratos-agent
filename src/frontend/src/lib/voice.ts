"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// The Web Speech API is not in TypeScript's DOM lib; type the parts we use.
interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  isFinal: boolean;
  0: SpeechAlternative;
}
interface SpeechResultEvent {
  resultIndex: number;
  results: ArrayLike<SpeechResult>;
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: SpeechResultEvent) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function recognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access is blocked. Allow it in the browser's site settings to talk to the agent.",
  "service-not-allowed": "Microphone access is blocked. Allow it in the browser's site settings to talk to the agent.",
  "audio-capture": "No microphone was found.",
  network: "Speech recognition needs a network connection.",
};

/**
 * Push-to-talk speech input using the browser's own speech recognition
 * (Chrome, Edge, Safari). `onTranscript` receives the running transcript,
 * interim words included; `stop()` resolves with the final text.
 */
export function useSpeechInput(onTranscript: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState("");
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const textRef = useRef("");
  const endWaiters = useRef<((text: string) => void)[]>([]);
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  useEffect(() => setSupported(recognitionCtor() !== null), []);

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || recRef.current) return;
    if (typeof window !== "undefined") window.speechSynthesis?.cancel();
    const rec = new Ctor();
    rec.lang = document.documentElement.lang && document.documentElement.lang !== "en" ? document.documentElement.lang : navigator.language || "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    textRef.current = "";
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      textRef.current = `${finalText}${interim}`.replace(/\s+/g, " ").trim();
      onTranscriptRef.current(textRef.current);
    };
    rec.onerror = (e) => {
      if (e.error !== "aborted" && e.error !== "no-speech") setError(ERRORS[e.error] ?? `Speech recognition failed (${e.error}).`);
    };
    rec.onend = () => {
      recRef.current = null;
      setListening(false);
      const text = textRef.current;
      endWaiters.current.splice(0).forEach((resolve) => resolve(text));
    };
    setError("");
    recRef.current = rec;
    setListening(true);
    try {
      rec.start();
    } catch {
      recRef.current = null;
      setListening(false);
    }
  }, []);

  const stop = useCallback((): Promise<string> => {
    const rec = recRef.current;
    if (!rec) return Promise.resolve(textRef.current);
    return new Promise((resolve) => {
      endWaiters.current.push(resolve);
      rec.stop();
    });
  }, []);

  useEffect(() => () => recRef.current?.abort(), []);

  return { supported, listening, error, start, stop };
}

/** Plain text for speech: drop code, markdown syntax and link targets. */
export function speakableText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*\|.*\|\s*$/gm, " ")
    .replace(/[#*_>~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function speak(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.slice(0, 4000));
  utterance.lang = navigator.language || "en-US";
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking() {
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}
