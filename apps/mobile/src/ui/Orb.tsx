// The orb: the agent's voice, hanging half-tucked at the screen edge and
// breathing while idle. Tap it and it slides out and listens; what you say
// goes to the agent like any message, and the reply comes back spoken in
// its voice. Tap again or say goodbye to put it away.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing, Platform, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Pressable } from "./Tap";
import { C, F } from "../theme";
import type { Session } from "../api";

type Phase = "idle" | "listening" | "thinking" | "speaking";

// Native speech and audio modules are absent in Expo Go. Probe for the native
// side first so the JS package is never evaluated without it, then degrade to text.
import { requireOptionalNativeModule } from "expo-modules-core";
function loadSpeech(): any | null {
  if (!requireOptionalNativeModule("ExpoSpeechRecognition")) return null;
  try { return require("expo-speech-recognition"); } catch { return null; }
}
function loadAudio(): any | null {
  if (!requireOptionalNativeModule("ExpoAudio")) return null;
  try { return require("expo-audio"); } catch { return null; }
}

export function Orb({ session, assistant, busy, lastReply, onSend, speak, canSpeak }: {
  session: Session; assistant: string; busy: boolean; lastReply: { seq: number; text: string } | null;
  onSend: (text: string) => void;
  speak?: { seq: number; text: string } | null;   // something the app wants read aloud (the Hub brief)
  canSpeak: boolean;                              // the server has a voice configured
}) {
  const insets = useSafeAreaInsets();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [heard, setHeard] = useState("");
  const [said, setSaid] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const breath = useRef(new Animated.Value(0)).current;
  const slide = useRef(new Animated.Value(0)).current;
  const speech = useRef<any>(loadSpeech());
  const audio = useRef<any>(loadAudio());
  const player = useRef<any>(null);
  const awaiting = useRef<number>(-1);

  useEffect(() => {
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(breath, { toValue: 1, duration: 1800, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      Animated.timing(breath, { toValue: 0, duration: 1800, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [breath]);

  useEffect(() => {
    Animated.spring(slide, { toValue: open ? 1 : 0, useNativeDriver: true, friction: 7 }).start();
  }, [open, slide]);

  // speech recognition events
  useEffect(() => {
    const sr = speech.current;
    if (!sr?.ExpoSpeechRecognitionModule) return;
    const subs = [
      sr.ExpoSpeechRecognitionModule.addListener("result", (ev: any) => {
        const t = ev.results?.[0]?.transcript ?? "";
        setHeard(t);
        if (ev.isFinal && t.trim()) {
          setPhase("thinking");
          awaiting.current = (lastReply?.seq ?? 0) + 1;
          if (/\b(goodbye|bye|that's all|thanks,? bye)\b/i.test(t)) { setOpen(false); setPhase("idle"); return; }
          onSend(t.trim());
        }
      }),
      sr.ExpoSpeechRecognitionModule.addListener("end", () => setPhase((p) => (p === "listening" ? "idle" : p))),
      sr.ExpoSpeechRecognitionModule.addListener("error", (e: any) => { setNote(e.message ?? "Couldn't hear that."); setPhase("idle"); }),
    ];
    return () => subs.forEach((s) => s.remove());
  }, [onSend, lastReply?.seq]);

  const listen = useCallback(async () => {
    const sr = speech.current;
    if (!sr?.ExpoSpeechRecognitionModule) { setNote("Voice needs the installed app, not Expo Go. Type instead."); return; }
    try {
      const perm = await sr.ExpoSpeechRecognitionModule.requestPermissionsAsync();
      if (!perm.granted) { setNote("Microphone permission is off."); return; }
      setHeard(""); setSaid(""); setNote(null); setPhase("listening");
      sr.ExpoSpeechRecognitionModule.start({ lang: "en-US", interimResults: true, continuous: false });
    } catch (e) { setNote(e instanceof Error ? e.message : String(e)); setPhase("idle"); }
  }, []);

  const toggle = useCallback(() => {
    if (open) { try { speech.current?.ExpoSpeechRecognitionModule?.stop(); } catch {} setOpen(false); setPhase("idle"); return; }
    setOpen(true);
    listen();
  }, [open, listen]);

  const say = useCallback((text: string, thenListen: boolean) => {
    setSaid(text);
    const a = audio.current;
    const url = `${session.url}/v1/voice/speak?text=${encodeURIComponent(text.slice(0, 1500))}`;
    if (!canSpeak) { setPhase("idle"); return; }
    if (!a?.createAudioPlayer) { setPhase("idle"); setNote("Audio needs the installed app; here's the text."); return; }
    try {
      setPhase("speaking");
      player.current?.remove?.();
      const p = a.createAudioPlayer({ uri: url, headers: { Authorization: `Bearer ${session.token}` } });
      player.current = p;
      p.addListener?.("playbackStatusUpdate", (st: any) => { if (st.didJustFinish) { setPhase("idle"); if (thenListen) listen(); } });
      p.play();
    } catch { setPhase("idle"); }
  }, [session, listen, canSpeak]);

  // speak the reply that answers what was said through the orb (never replies from before it opened)
  useEffect(() => {
    if (!open || !lastReply || awaiting.current < 0 || lastReply.seq < awaiting.current) return;
    awaiting.current = -1;
    say(lastReply.text, true);
  }, [lastReply, open, say]);

  // read something the app asked for (the Hub brief's Play)
  useEffect(() => {
    if (!speak || !speak.text) return;
    setOpen(true); setHeard(""); setNote(null);
    say(speak.text, false);
  }, [speak, say]);

  const scale = breath.interpolate({ inputRange: [0, 1], outputRange: [1, 1.06] });
  const tx = slide.interpolate({ inputRange: [0, 1], outputRange: [26, 0] });
  const label = phase === "listening" ? "LISTENING" : phase === "thinking" || busy ? "THINKING" : phase === "speaking" ? "SPEAKING" : "TAP TO TALK";

  return (
    <>
      {open ? (
        <View style={[o.dock, { bottom: 118 + Math.max(insets.bottom - 8, 0) }]}>
          <View style={o.head}>
            <View style={o.waveRow}>
              {[10, 16, 8, 14, 11, 17, 9].map((h, i) => (
                <Animated.View key={i} style={[o.waveBar, { height: phase === "idle" ? 4 : h,
                  opacity: breath.interpolate({ inputRange: [0, 1], outputRange: i % 2 ? [0.35, 0.95] : [0.95, 0.35] }) }]} />
              ))}
            </View>
            <Text style={o.label}>{assistant.toUpperCase()}  ·  {label}</Text>
            <Pressable onPress={toggle} hitSlop={12} style={o.close}><Text style={{ color: "rgba(244,242,250,0.6)", fontSize: 13 }}>✕</Text></Pressable>
          </View>
          {heard ? <Text style={o.heard} numberOfLines={2}>“{heard}”</Text> : null}
          {said ? <Text style={o.said} numberOfLines={4}>{said}</Text> : !heard ? <Text style={o.hint}>{note ?? "Say it. I'm listening."}</Text> : null}
          {note && heard ? <Text style={o.hint}>{note}</Text> : null}
          {phase === "idle" && !busy ? (
            <Pressable style={o.again} feel="control" onPress={listen}><Text style={o.againText}>Speak again</Text></Pressable>
          ) : null}
        </View>
      ) : null}
      <Animated.View style={[o.ballWrap, { bottom: 128 + Math.max(insets.bottom - 8, 0), transform: [{ translateX: tx }, { scale }] }]}>
        <Pressable onPress={toggle} hitSlop={10} feel="control">
          <LinearGradient colors={["#DCD2FF", "#8F7CFF", "#4B3AA8"]} start={{ x: 0.2, y: 0.1 }} end={{ x: 0.9, y: 1 }} style={o.ball} />
        </Pressable>
      </Animated.View>
    </>
  );
}

const o = StyleSheet.create({
  ballWrap: { position: "absolute", right: -6, zIndex: 50 },
  ball: { width: 56, height: 56, borderRadius: 28, shadowColor: "#9F8CFF", shadowOpacity: 0.9, shadowRadius: 18, shadowOffset: { width: 0, height: 0 },
    borderWidth: 1, borderColor: "rgba(199,184,255,0.4)" },
  dock: { position: "absolute", left: 12, right: 12, backgroundColor: "rgba(14,12,24,0.98)", borderWidth: 1, borderColor: "rgba(199,184,255,0.16)",
    borderRadius: 22, paddingHorizontal: 18, paddingVertical: 14, zIndex: 60, gap: 8,
    shadowColor: "#000", shadowOpacity: 0.5, shadowRadius: 24, shadowOffset: { width: 0, height: 8 } },
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  waveRow: { flexDirection: "row", alignItems: "center", gap: 2.5, height: 18 },
  waveBar: { width: 2.5, borderRadius: 2, backgroundColor: "#C7B8FF" },
  label: { flex: 1, fontFamily: F.mono, fontSize: 10, letterSpacing: 3, color: C.muted, marginLeft: 4 },
  close: { padding: 4 },
  heard: { fontFamily: F.sans, fontSize: 14, color: C.body, fontStyle: "italic" },
  said: { fontFamily: F.sans, fontSize: 15, lineHeight: 21, color: C.text },
  hint: { fontFamily: F.sans, fontSize: 13, color: C.muted },
  again: { alignSelf: "flex-start", paddingHorizontal: 12, paddingVertical: 6, borderRadius: 100, backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1, borderColor: "rgba(255,255,255,0.14)" },
  againText: { fontFamily: F.mono, fontSize: 10, letterSpacing: 2, color: C.accent },
});
