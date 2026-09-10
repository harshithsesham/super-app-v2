// The Browser card from the app: globe icon, "Browser" and a short status
// like "Selecting seats…", the live screenshot, and an Open browser button
// that shows the page full-screen.
import React, { useState } from "react";
import { Image, Modal, StyleSheet, Text, View } from "react-native";
import { Pressable } from "./Tap";
import { C, R } from "../theme";
import type { BrowserTask } from "../api";

export function BrowserCard({ task, onStop }: { task: BrowserTask; onStop?: () => void }) {
  const [open, setOpen] = useState(false);
  const live = task.status === "running" || task.status === "queued";
  const shot = task.screenshot ? { uri: `data:image/jpeg;base64,${task.screenshot}` } : null;
  const status = task.status === "needs_user" ? "Needs you" : task.status === "completed" ? "Done"
    : task.status === "failed" ? "Couldn't finish" : task.status === "stopped" ? "Stopped" : `${task.status_title}…`.replace("……", "…");
  return (
    <View style={s.card}>
      <View style={s.head}>
        <View style={s.icon}><Text style={{ fontSize: 20 }}>🌐</Text></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Browser</Text>
          <Text style={s.sub} numberOfLines={1}>{status}</Text>
        </View>
      </View>
      {shot ? <Image source={shot} style={s.shot} resizeMode="cover" /> : <View style={[s.shot, s.blank]} />}
      <View style={s.actions}>
        <Pressable style={s.open} feel="control" onPress={() => setOpen(true)}>
          <Text style={s.openText}>Open browser</Text>
        </Pressable>
        {live && onStop ? (
          <Pressable style={s.stop} feel="control" onPress={onStop}><Text style={s.stopText}>Stop</Text></Pressable>
        ) : null}
      </View>
      <Modal visible={open} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setOpen(false)}>
        <View style={s.full}>
          <View style={s.fullHead}>
            <Text style={s.fullTitle} numberOfLines={1}>{task.title}</Text>
            <Text style={s.fullUrl} numberOfLines={1}>{task.url}</Text>
          </View>
          {shot ? <Image source={shot} style={s.fullShot} resizeMode="contain" /> : null}
          <Text style={s.fullNote}>Live view. Taking over the session comes in a later build.</Text>
          <Pressable style={s.done} feel="control" onPress={() => setOpen(false)}><Text style={s.doneText}>Done</Text></Pressable>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: C.bubbleAgent, borderRadius: R.card, padding: 12, gap: 10, alignSelf: "stretch" },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: C.blueTint, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "600", color: C.text },
  sub: { fontSize: 15, color: C.muted, marginTop: 1 },
  shot: { width: "100%", aspectRatio: 1024 / 1100, borderRadius: 14, backgroundColor: C.surface },
  blank: { alignItems: "center", justifyContent: "center" },
  actions: { flexDirection: "row", gap: 8 },
  open: { flex: 1, backgroundColor: C.surface, borderRadius: R.pill, paddingVertical: 14, alignItems: "center" },
  openText: { fontSize: 17, fontWeight: "600", color: C.text },
  stop: { backgroundColor: C.surface, borderRadius: R.pill, paddingVertical: 14, paddingHorizontal: 18, alignItems: "center" },
  stopText: { fontSize: 17, fontWeight: "600", color: C.red },
  full: { flex: 1, backgroundColor: C.bg, padding: 16, paddingTop: 20, gap: 10 },
  fullHead: { gap: 2 },
  fullTitle: { fontSize: 18, fontWeight: "600", color: C.text },
  fullUrl: { fontSize: 13, color: C.muted },
  fullShot: { flex: 1, width: "100%", borderRadius: 14, backgroundColor: C.surface },
  fullNote: { fontSize: 13, color: C.muted, textAlign: "center" },
  done: { alignSelf: "center", backgroundColor: C.text, borderRadius: R.pill, paddingHorizontal: 28, paddingVertical: 14, marginBottom: 10 },
  doneText: { color: C.onAccent, fontSize: 16, fontWeight: "600" },
});
