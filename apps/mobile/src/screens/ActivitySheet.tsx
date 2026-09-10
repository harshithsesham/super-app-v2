// Tapping the avatar opens the activity log: what the agent is doing now,
// what it has done, and its background workers.
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, Modal, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { Avatar } from "../ui/Avatar";
import { C, R } from "../theme";
import type { ActivityEvent, Api, Subagent } from "../api";
import { describe } from "./ChatScreen";

function when(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function ActivitySheet({ api, assistant, visible, onClose, liveCount }: {
  api: Api; assistant: string; visible: boolean; onClose: () => void; liveCount: number;
}) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [subs, setSubs] = useState<Subagent[]>([]);
  const [status, setStatus] = useState("idle");
  const load = useCallback(async () => {
    try { const a = await api.activity(); setEvents(a.events); setSubs(a.subagents); setStatus(a.status); } catch {}
  }, [api]);
  useEffect(() => { if (visible) load(); }, [visible, load, liveCount]);

  const rows = [...events].reverse().map((e) => ({ ...e, line: e.kind === "tool_result" ? null : describe(e.kind, e.data) })).filter((e) => e.line);

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={s.root}>
        <View style={s.head}>
          <Avatar size={72} />
          <Text style={s.name}>{assistant}</Text>
          <Text style={s.status}>{status === "running" ? "Working now" : "Idle"}</Text>
        </View>
        {subs.length ? (
          <View style={s.card}>
            <Text style={s.section}>Background work</Text>
            {subs.map((su) => (
              <View key={su.spawn_id} style={s.subRow}>
                <View style={[s.dot, { backgroundColor: su.status === "running" ? C.amber : su.status === "done" ? C.green : C.muted }]} />
                <Text style={s.subLabel} numberOfLines={1}>{su.label}</Text>
                <Text style={s.subStatus}>{su.status}</Text>
              </View>
            ))}
          </View>
        ) : null}
        <Text style={[s.section, { marginLeft: 20 }]}>Activity</Text>
        <FlatList
          data={rows}
          keyExtractor={(e, i) => `${e.ts}-${i}`}
          contentContainerStyle={s.list}
          ListEmptyComponent={<Text style={s.empty}>Nothing yet.</Text>}
          renderItem={({ item }) => (
            <View style={s.row}>
              <Text style={s.line}>{item.line}</Text>
              <Text style={s.time}>{when(item.ts)}</Text>
            </View>
          )}
        />
        <Pressable style={s.close} feel="control" onPress={onClose}><Text style={s.closeText}>Done</Text></Pressable>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg, paddingTop: 16 },
  head: { alignItems: "center", gap: 6, paddingVertical: 12 },
  name: { fontSize: 20, fontWeight: "600", color: C.text },
  status: { fontSize: 15, color: C.muted },
  card: { marginHorizontal: 16, backgroundColor: C.surface, borderRadius: R.card, padding: 14, gap: 8, marginBottom: 8 },
  section: { fontSize: 13, fontWeight: "600", color: C.muted, marginBottom: 4 },
  subRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  subLabel: { flex: 1, fontSize: 16, color: C.text },
  subStatus: { fontSize: 13, color: C.muted },
  list: { paddingHorizontal: 16, paddingBottom: 90 },
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", backgroundColor: C.surface, borderRadius: 14, paddingHorizontal: 14, paddingVertical: 12, marginBottom: 6 },
  line: { flex: 1, fontSize: 16, color: C.text },
  time: { fontSize: 13, color: C.muted, marginLeft: 12 },
  empty: { fontSize: 16, color: C.muted, textAlign: "center", marginTop: 30 },
  close: { position: "absolute", bottom: 30, alignSelf: "center", backgroundColor: C.text, borderRadius: R.pill, paddingHorizontal: 28, paddingVertical: 14 },
  closeText: { color: "#fff", fontSize: 16, fontWeight: "600" },
});
