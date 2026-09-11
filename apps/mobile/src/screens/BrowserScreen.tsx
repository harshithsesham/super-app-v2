// The Browser connector's live view: the agent's own browser on your phone.
// Tap the page, type into the focused field, scroll, go to a URL. In task mode
// you are covering for Muse (a sign-in, a checkout, a captcha) and hand the
// page back when done; in free mode you are just using its browser, for
// instance to sign into a site it will use later.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Image, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text, TextInput, View, useWindowDimensions } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "../ui/Tap";
import { C, F } from "../theme";
import type { Api, BrowserLive, BrowserInput } from "../api";

export function BrowserScreen({ api, mode, taskId, onClose }: { api: Api; mode: "task" | "free"; taskId?: string; onClose: () => void }) {
  const [live, setLive] = useState<BrowserLive | null>(null);
  const [busy, setBusy] = useState(false);
  const [typing, setTyping] = useState<"text" | "url" | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const [handing, setHanding] = useState(false);
  const { width } = useWindowDimensions();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  const busyRef = useRef(false);

  const refresh = useCallback(async () => {
    try { const l = await api.browserLive(); if (alive.current) setLive(l); } catch {}
  }, [api]);

  // open (free mode) or attach (task mode), then poll while the view is up
  useEffect(() => {
    alive.current = true;
    (async () => {
      try {
        if (mode === "free") setLive(await api.browserOpen());
        else await refresh();
      } catch {}
    })();
    const tick = () => { timer.current = setTimeout(async () => { if (!busyRef.current) await refresh(); if (alive.current) tick(); }, 1500); };
    tick();
    return () => { alive.current = false; if (timer.current) clearTimeout(timer.current); };
  }, [api, mode, refresh]);

  const send = useCallback(async (cmd: BrowserInput) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try { const l = await api.browserInput(cmd); if (alive.current) setLive(l); } catch {}
    busyRef.current = false; setBusy(false);
  }, [api]);

  const control = !!live?.can_control;
  const shotW = width;
  const shotH = live ? shotW * (live.height / live.width) : shotW * 1.07;
  const scale = live ? live.width / shotW : 1;

  const onTap = (e: { nativeEvent: { locationX: number; locationY: number } }) => {
    if (!control) return;
    send({ type: "tap", x: Math.round(e.nativeEvent.locationX * scale), y: Math.round(e.nativeEvent.locationY * scale) });
  };

  const takeover = async () => {
    if (!taskId || busy) return;
    setBusy(true);
    try { setLive(await api.browserTakeover(taskId)); } catch {}
    setBusy(false);
  };
  const handback = async () => {
    if (!taskId) return;
    setHanding(true);
    try { await api.browserHandback(taskId, note); } catch {}
    setHanding(false);
    onClose();
  };
  const finish = async () => {
    if (mode === "free") { try { await api.browserClose(); } catch {} }
    onClose();
  };

  const status = !live || live.mode === "none" ? "Opening…"
    : live.mode === "task" && !control ? `Muse is working: ${live.status_title ?? ""}`
    : "You're in control";

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={s.head}>
        <Pressable onPress={finish} feel="control" hitSlop={10}><Text style={s.headBtn}>{mode === "free" ? "Done" : "Close"}</Text></Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={s.title} numberOfLines={1}>{live?.title || "Browser"}</Text>
          <Text style={s.url} numberOfLines={1}>{live?.url || ""}</Text>
        </View>
        <Pressable onPress={() => { setTyping(typing === "url" ? null : "url"); setDraft(""); }} feel="control" hitSlop={10}>
          <Text style={s.headBtn}>Go to…</Text>
        </Pressable>
      </View>
      <View style={s.statusRow}>
        <Text style={[s.status, control && { color: C.green }]}>{status}</Text>
        {live?.mode === "task" && !control ? (
          <Pressable style={s.takeover} feel="control" onPress={takeover}><Text style={s.takeoverText}>{busy ? "Pausing…" : "Take over"}</Text></Pressable>
        ) : null}
      </View>
      {live?.question && control ? <Text style={s.question}>{live.question}</Text> : null}

      <ScrollView style={{ flex: 1 }} maximumZoomScale={3} minimumZoomScale={1} bouncesZoom contentContainerStyle={{ alignItems: "center" }}>
        <Pressable onPress={onTap} disabled={!control} style={{ width: shotW, height: shotH }}>
          {live?.screenshot ? (
            <Image source={{ uri: `data:image/jpeg;base64,${live.screenshot}` }} style={{ width: shotW, height: shotH }} resizeMode="contain" />
          ) : (
            <View style={[s.blank, { width: shotW, height: shotH }]}><ActivityIndicator color={C.accent} /></View>
          )}
        </Pressable>
      </ScrollView>

      {typing ? (
        <View style={s.typeRow}>
          <TextInput style={s.typeInput} value={draft} onChangeText={setDraft} autoFocus autoCapitalize="none" autoCorrect={false}
            keyboardType={typing === "url" ? "url" : "default"} placeholder={typing === "url" ? "https://…" : "Type into the focused field"}
            placeholderTextColor={C.muted} returnKeyType="go"
            onSubmitEditing={() => { const t = draft; setTyping(null); setDraft(""); send(typing === "url" ? { type: "navigate", url: t } : { type: "type", text: t, submit: true }); }} />
          <Pressable feel="control" onPress={() => { const t = draft; setTyping(null); setDraft(""); send(typing === "url" ? { type: "navigate", url: t } : { type: "type", text: t, submit: false }); }}>
            <Text style={s.headBtn}>{typing === "url" ? "Go" : "Type"}</Text>
          </Pressable>
        </View>
      ) : null}

      <View style={s.toolbar}>
        <Tool label="‹" onPress={() => send({ type: "back" })} disabled={!control} />
        <Tool label="↑" onPress={() => send({ type: "scroll", dy: -600 })} disabled={!control} />
        <Tool label="↓" onPress={() => send({ type: "scroll", dy: 600 })} disabled={!control} />
        <Tool label="Aa" onPress={() => { setTyping(typing === "text" ? null : "text"); setDraft(""); }} disabled={!control} />
        <Tool label="⏎" onPress={() => send({ type: "key", key: "Enter" })} disabled={!control} />
        {busy ? <ActivityIndicator color={C.accent} style={{ marginLeft: 6 }} /> : null}
      </View>

      {mode === "task" && control ? (
        <View style={s.handRow}>
          <TextInput style={s.noteInput} value={note} onChangeText={setNote} placeholder="Note for Muse (optional)" placeholderTextColor={C.muted} />
          <Pressable style={s.hand} feel="control" onPress={handback} disabled={handing}>
            <Text style={s.handText}>{handing ? "Handing back…" : "Hand back to Muse"}</Text>
          </Pressable>
        </View>
      ) : null}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Tool({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable style={[s.tool, disabled && { opacity: 0.35 }]} feel="control" onPress={onPress} disabled={disabled}>
      <Text style={s.toolText}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  head: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 14, paddingVertical: 8 },
  headBtn: { color: C.accent, fontSize: 16, fontWeight: "600" },
  title: { color: C.text, fontSize: 15, fontWeight: "600" },
  url: { color: C.muted, fontSize: 12, fontFamily: F.mono },
  statusRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 14, paddingBottom: 6 },
  status: { color: C.muted, fontSize: 13, fontFamily: F.mono, letterSpacing: 1 },
  takeover: { backgroundColor: C.accent, borderRadius: 999, paddingVertical: 8, paddingHorizontal: 16 },
  takeoverText: { color: C.onAccent, fontWeight: "600" },
  question: { color: C.body, fontSize: 14, paddingHorizontal: 14, paddingBottom: 8 },
  blank: { alignItems: "center", justifyContent: "center", backgroundColor: C.surface },
  typeRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 10, backgroundColor: C.surface },
  typeInput: { flex: 1, color: C.text, fontSize: 16, padding: 10, backgroundColor: C.bg, borderRadius: 10 },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderTopWidth: 1, borderColor: C.border },
  tool: { minWidth: 48, height: 40, borderRadius: 12, backgroundColor: C.surface, alignItems: "center", justifyContent: "center", paddingHorizontal: 12 },
  toolText: { color: C.text, fontSize: 17, fontWeight: "600" },
  handRow: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, paddingBottom: 24 },
  noteInput: { flex: 1, color: C.text, fontSize: 15, padding: 12, backgroundColor: C.surface, borderRadius: 12 },
  hand: { backgroundColor: C.accent, borderRadius: 999, paddingVertical: 12, paddingHorizontal: 16 },
  handText: { color: C.onAccent, fontWeight: "600" },
});
