// First launch after sign-in: three short steps, then the agent opens the
// conversation itself. Writes USER.md and IDENTITY.md in the user's cell.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "../ui/Tap";
import { Avatar } from "../ui/Avatar";
import { Stars } from "../ui/Stars";
import { C, F } from "../theme";
import type { Api } from "../api";

const VIBES: { key: string; label: string; blurb: string }[] = [
  { key: "warm and direct", label: "Warm", blurb: "Friendly, gets to the point." },
  { key: "direct and dry", label: "Direct", blurb: "Short answers, no fluff." },
  { key: "playful and sharp", label: "Playful", blurb: "Light touch, still sharp." },
  { key: "calm and thorough", label: "Calm", blurb: "Measured, careful, complete." },
];

export function OnboardingScreen({ api, defaultName, onDone }: { api: Api; defaultName?: string; onDone: (assistant: string) => void }) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(defaultName ?? "");
  const [callThem, setCallThem] = useState("");
  const [assistant, setAssistant] = useState("Muse");
  const [vibe, setVibe] = useState(VIBES[0].key);
  const [plate, setPlate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const finish = async () => {
    if (busy) return;
    setBusy(true); setError(null);
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const r = await api.onboard({ name: name.trim(), call_them: callThem.trim(), assistant: assistant.trim() || "Muse", vibe, plate: plate.trim(), timezone: tz });
      onDone(r.assistant);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const steps = [
    {
      title: "What should I call you?",
      sub: "Your name, and a shorter one if you like.",
      valid: name.trim().length > 0,
      body: (
        <>
          <TextInput style={s.input} value={name} onChangeText={setName} placeholder="Your name" placeholderTextColor={C.muted} autoFocus autoCapitalize="words" autoCorrect={false} returnKeyType="next" />
          <TextInput style={s.input} value={callThem} onChangeText={setCallThem} placeholder="What friends call you (optional)" placeholderTextColor={C.muted} autoCapitalize="words" autoCorrect={false} />
        </>
      ),
    },
    {
      title: "Name your agent",
      sub: "It has its own computer, memory, and browser. Give it a name and a vibe.",
      valid: true,
      body: (
        <>
          <TextInput style={s.input} value={assistant} onChangeText={setAssistant} placeholder="Muse" placeholderTextColor={C.muted} autoCapitalize="words" autoCorrect={false} />
          <View style={s.chips}>
            {VIBES.map((v) => (
              <Pressable key={v.key} feel="control" onPress={() => setVibe(v.key)} style={[s.chip, vibe === v.key && s.chipOn]}>
                <Text style={[s.chipLabel, vibe === v.key && s.chipLabelOn]}>{v.label}</Text>
                <Text style={s.chipBlurb}>{v.blurb}</Text>
              </Pressable>
            ))}
          </View>
        </>
      ),
    },
    {
      title: "What's on your plate?",
      sub: "A few lines is plenty. It will remember, and get to work.",
      valid: true,
      body: (
        <TextInput style={[s.input, s.multi]} value={plate} onChangeText={setPlate} multiline placeholder="e.g. Ship the app this month, keep on top of email, book a trip to Austin…" placeholderTextColor={C.muted} />
      ),
    },
  ];
  const cur = steps[step];
  const last = step === steps.length - 1;

  return (
    <SafeAreaView style={s.root}>
      <Stars />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
          <View style={{ alignItems: "center", marginBottom: 18 }}><Avatar size={72} /></View>
          <Text style={s.kicker}>{`STEP ${step + 1} OF ${steps.length}`}</Text>
          <Text style={s.title}>{cur.title}</Text>
          <Text style={s.sub}>{cur.sub}</Text>
          {cur.body}
          {error ? <Text style={s.error}>{error}</Text> : null}
          <View style={s.row}>
            {step > 0 ? (
              <Pressable style={s.btnGhost} feel="control" onPress={() => setStep(step - 1)}><Text style={s.btnGhostText}>Back</Text></Pressable>
            ) : <View />}
            <Pressable style={[s.btn, !cur.valid && { opacity: 0.4 }]} feel="control" disabled={!cur.valid || busy}
              onPress={() => (last ? finish() : setStep(step + 1))}>
              <Text style={s.btnText}>{busy ? "Setting up…" : last ? (plate.trim() ? "Let's go" : "Skip for now") : "Continue"}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  body: { flexGrow: 1, justifyContent: "center", padding: 28, gap: 12 },
  kicker: { fontFamily: F.mono, fontSize: 11, letterSpacing: 3, color: C.muted, textAlign: "center" },
  title: { fontSize: 28, lineHeight: 34, fontWeight: "700", color: C.text, textAlign: "center" },
  sub: { fontSize: 15, lineHeight: 22, color: C.body, textAlign: "center", marginBottom: 8 },
  input: { backgroundColor: C.surface, borderRadius: 14, padding: 14, fontSize: 16, color: C.text, borderWidth: 1, borderColor: C.border },
  multi: { minHeight: 120, textAlignVertical: "top" },
  chips: { gap: 8 },
  chip: { backgroundColor: C.surface, borderRadius: 14, padding: 12, borderWidth: 1, borderColor: C.border },
  chipOn: { borderColor: C.accent, backgroundColor: "rgba(199,184,255,0.10)" },
  chipLabel: { fontSize: 15, fontWeight: "600", color: C.text },
  chipLabelOn: { color: C.accent },
  chipBlurb: { fontSize: 13, color: C.muted, marginTop: 2 },
  error: { color: C.red, fontSize: 14, textAlign: "center" },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 8 },
  btn: { backgroundColor: C.accent, borderRadius: 999, paddingVertical: 14, paddingHorizontal: 28 },
  btnText: { color: C.onAccent, fontSize: 16, fontWeight: "600" },
  btnGhost: { paddingVertical: 14, paddingHorizontal: 12 },
  btnGhostText: { color: C.muted, fontSize: 15 },
});
