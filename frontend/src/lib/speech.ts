"use client";

import { useEffect, useRef, useState } from "react";

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
  const recognitionRef = useRef<MinimalSpeechRecognition | null>(null);
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
        callbackRef.current(lastResult[0].transcript);
      }
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);

    recognitionRef.current = recognition;
  }, []);

  const start = () => {
    if (!recognitionRef.current || listening) return;
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

  return { supported, listening, start, stop };
}

export function speak(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

export function cancelSpeech() {
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}
