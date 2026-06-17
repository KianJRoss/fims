import { useEffect, useRef, useState } from "react";
import { Mic } from "lucide-react";

type Props = {
  onResult: (text: string) => void;
  className?: string;
};

function getSpeechRecognitionCtor(): (new () => any) | null {
  if (typeof window === "undefined") return null;
  return (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition || null;
}

export default function VoiceInputButton({ onResult, className }: Props) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const supported = getSpeechRecognitionCtor() !== null;

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop?.();
    };
  }, []);

  const toggle = () => {
    if (!supported) return;
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;
    const recognition = new Ctor();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onresult = (event: any) => {
      const transcript = event.results?.[0]?.[0]?.transcript ?? "";
      if (transcript.trim()) onResult(transcript.trim());
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
    } catch {
      setListening(false);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={!supported}
      title={
        supported
          ? listening
            ? "Listening... click to stop"
            : "Click to dictate"
          : "Voice input not supported in this browser"
      }
      className={`inline-flex items-center justify-center rounded-xl border p-2.5 transition ${
        listening
          ? "border-orange-500/60 bg-orange-500/10 text-orange-300"
          : "border-gray-700 bg-gray-950 text-gray-400 hover:border-orange-500/40 hover:text-orange-200"
      } disabled:cursor-not-allowed disabled:opacity-40 ${className ?? ""}`}
    >
      <Mic className={`h-4 w-4 ${listening ? "animate-pulse" : ""}`} />
    </button>
  );
}
