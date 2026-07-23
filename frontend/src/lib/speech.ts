"use client";

import { useEffect, useRef, useState } from "react";
import { transcribeAudio } from "./chat";

// The Web Speech API's SpeechRecognition isn't in TS's standard DOM lib
// (it's still non-standard / webkit-prefixed in most browsers) -- minimal
// shape declared here rather than pulling in a whole ambient-types package.
type SpeechRecognitionAlternative = { transcript: string };
type SpeechRecognitionResult = {
  isFinal: boolean;
  length: number;
  [index: number]: SpeechRecognitionAlternative;
};
type SpeechRecognitionResultList = { length: number; [index: number]: SpeechRecognitionResult };
type SpeechRecognitionEvent = { resultIndex: number; results: SpeechRecognitionResultList };

interface MinimalSpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

declare global {
  interface Window {
    SpeechRecognition?: new () => MinimalSpeechRecognition;
    webkitSpeechRecognition?: new () => MinimalSpeechRecognition;
  }
}

export function useSpeechRecognition(onFinalResult: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const recognitionRef = useRef<MinimalSpeechRecognition | null>(null);
  const gotResultRef = useRef(false);
  const callbackRef = useRef(onFinalResult);
  useEffect(() => {
    callbackRef.current = onFinalResult;
  }, [onFinalResult]);

  // Feature detection must default false during SSR/hydration and confirm
  // client-side in this effect -- there's no render-time way to know this.
  useEffect(() => {
    const Ctor = window.SpeechRecognition ?? window.webkitSpeechRecognition;
    if (!Ctor) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSupported(false);
      return;
    }
    setSupported(true);

    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const lastResult = event.results[event.results.length - 1];
      if (lastResult.isFinal) {
        gotResultRef.current = true;
        callbackRef.current(lastResult[0].transcript);
      }
    };
    recognition.onend = () => {
      setListening(false);
      // This browser's recognition is cloud-based (audio round-trips to a
      // speech service), not purely on-device -- a network hiccup, a denied
      // mic permission, or genuine silence can all end the session with no
      // error event at all, just a resultless onend. Previously this looked
      // identical to a successful, silent no-op: the mic just stopped and
      // nothing was ever sent, with no way to tell why.
      if (!gotResultRef.current) setLastError("no-speech");
    };
    recognition.onerror = (event) => setLastError(event.error || "unknown");

    recognitionRef.current = recognition;
  }, []);

  const start = () => {
    if (!recognitionRef.current || listening) return;
    gotResultRef.current = false;
    setLastError(null);
    try {
      recognitionRef.current.start();
      setListening(true);
    } catch {
      // Browser throws InvalidStateError if a session is already active
      // (e.g. a fast double-click racing ahead of the `listening` state
      // update) -- harmless to ignore, the existing session continues.
    }
  };

  const stop = () => {
    recognitionRef.current?.stop();
  };

  return { supported, listening, lastError, start, stop };
}

// Fallback for browsers with no SpeechRecognition (Safari, Firefox, most
// mobile browsers): record with the universally-supported MediaRecorder API
// and transcribe server-side via Groq Whisper (see backend/services/transcribe.py).
// Slower (upload + transcription round-trip) than on-device recognition, but
// it's the only voice path these browsers have at all.
function useMediaRecorderFallback(onFinalResult: (text: string) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [lastError, setLastError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const callbackRef = useRef(onFinalResult);
  useEffect(() => {
    callbackRef.current = onFinalResult;
  }, [onFinalResult]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSupported(
      typeof window !== "undefined" &&
        !!window.MediaRecorder &&
        !!navigator.mediaDevices?.getUserMedia
    );
  }, []);

  const start = async () => {
    if (listening || transcribing) return;
    setLastError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        setListening(false);
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const ext = recorder.mimeType?.includes("mp4") ? "mp4" : "webm";
        setTranscribing(true);
        try {
          const text = await transcribeAudio(blob, `voice-input.${ext}`);
          if (text) callbackRef.current(text);
          else setLastError("empty transcript");
        } catch (err) {
          // Previously silent -- a transcription failure (e.g. the Whisper
          // call hitting the same Groq rate limit as chat) looked identical
          // to the user just not having said anything.
          setLastError(err instanceof Error ? err.message : "transcription failed");
        } finally {
          setTranscribing(false);
        }
      };

      recorderRef.current = recorder;
      recorder.start();
      setListening(true);
    } catch {
      // getUserMedia rejected (permission denied, no mic) -- nothing to
      // recover into, the mic button just goes back to idle.
      setListening(false);
      setLastError("microphone permission denied");
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
  };

  return { supported, listening: listening || transcribing, lastError, start, stop };
}

// Single entry point for the mic button: use native on-device recognition
// when the browser has it (instant, free), otherwise fall back to
// record-and-upload so Safari/Firefox/mobile get voice input too (§7).
export function useVoiceInput(onFinalResult: (text: string) => void) {
  const native = useSpeechRecognition(onFinalResult);
  const fallback = useMediaRecorderFallback(onFinalResult);
  return native.supported ? native : fallback;
}

export function speak(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  // Chrome bug: cancel() doesn't clear its internal speaking state
  // synchronously, so a speak() called immediately after can race it and
  // get silently dropped -- the utterance never plays and nothing errors.
  // A short delay avoids the race (a known, long-standing Chromium issue).
  setTimeout(() => window.speechSynthesis.speak(new SpeechSynthesisUtterance(text)), 50);
}

// A response after VOICE input goes through: click mic (a real user gesture)
// -> browser-internal speech recognition -> onresult callback -> speak().
// That onresult callback fires as an async, browser-internal event, not as a
// trusted gesture -- some browsers only allow speechSynthesis.speak() to
// actually produce audio once it's been "unlocked" by a genuine gesture-
// linked call earlier in the session, and silently ignore it otherwise.
// Typed messages don't have this problem (Send's click handler IS the
// trusted gesture), which is exactly the difference observed live: typed
// responses spoke fine, voice-triggered ones arrived as text but stayed
// silent. Call this synchronously from the mic button's own onClick.
export function unlockSpeechSynthesis() {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const unlock = new SpeechSynthesisUtterance(" ");
  unlock.volume = 0;
  window.speechSynthesis.speak(unlock);
}

export function cancelSpeech() {
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}
