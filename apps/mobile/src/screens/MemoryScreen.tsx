// Memory: the files the user can read and edit directly, per the design
// post. Read-only in this build; editing comes with the file endpoints.
import React, { useCallback, useEffect, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { BackIcon } from "../ui/Icons";
import { C, R } from "../theme";
import type { Api } from "../api";

export function MemoryScreen({ api, onBack }: { api: Api; onBack: () => void }) {
  const [mem, setMem] = useState<{ "MEMORY.md": string; today: string; people: string } | null>(null);
  const load = useCallback(async () => { try { setMem(await api.memory()); } catch {} }, [api]);
  useEffect(() => { load(); }, [load]);
  const block = (title: string, body: string | undefined) => (
    <View style={s.group}>
      <Text style={s.section}>{title}</Text>
      <View style={s.card}><Text style={s.mono}>{(body ?? "").trim() || "Nothing here yet."}</Text></View>
    </View>
  );
  return (
    <View style={s.root}>
      <View style={s.header}>
        <Pressable style={s.back} feel="control" onPress={onBack}><BackIcon /></Pressable>
        <Text style={s.title}>Memory</Text>
        <View style={{ width: 44 }} />
      </View>
      <ScrollView contentContainerStyle={s.list}>
        {block("MEMORY.md", mem?.["MEMORY.md"])}
        {block("Today", mem?.today)}
        {block("People", mem?.people)}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8 },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: C.surface, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 20, fontWeight: "600", color: C.text },
  list: { paddingHorizontal: 16, paddingBottom: 60, gap: 14 },
  group: { gap: 8 },
  section: { fontSize: 13, fontWeight: "600", color: C.muted, marginLeft: 4 },
  card: { backgroundColor: C.surface, borderRadius: R.card, padding: 16 },
  mono: { fontFamily: "Menlo", fontSize: 13, lineHeight: 19, color: C.body },
});
