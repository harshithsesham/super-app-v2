// Goals: durable outcomes with checkboxes, grouped by category, with the
// agent's plan under each. Tap the box to complete; tap the row to discuss.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { C, R } from "../theme";
import type { Api, Goal } from "../api";

export function GoalsScreen({ api, onDiscuss }: { api: Api; onDiscuss: (goal: Goal) => void }) {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [draft, setDraft] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setGoals((await api.goals()).goals); } catch {}
    setRefreshing(false);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const save = useCallback(async (next: Goal[]) => {
    setGoals(next);
    try { await api.setGoals(next); } catch {}
  }, [api]);

  const groups = useMemo(() => {
    const m = new Map<string, Goal[]>();
    for (const g of goals) m.set(g.category, [...(m.get(g.category) ?? []), g]);
    return [...m.entries()];
  }, [goals]);

  return (
    <ScrollView style={s.root} contentContainerStyle={s.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}>
      <Text style={s.h1}>Goals</Text>
      {groups.map(([cat, items]) => (
        <View key={cat} style={s.group}>
          <Text style={s.cat}>{cat}</Text>
          <View style={s.card}>
            {items.map((g, i) => (
              <Pressable key={g.id} style={[s.row, i < items.length - 1 && s.rowBorder]} onPress={() => onDiscuss(g)}>
                <Pressable feel="control" hitSlop={10}
                  onPress={() => save(goals.map((x) => (x.id === g.id ? { ...x, done: !x.done } : x)))}>
                  <View style={[s.box, g.done && s.boxDone]}>{g.done ? <Text style={s.tick}>✓</Text> : null}</View>
                </Pressable>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[s.title, g.done && s.titleDone]}>{g.title}</Text>
                  {g.plan?.length ? <Text style={s.plan} numberOfLines={2}>{g.plan.join(" · ")}</Text> : null}
                </View>
              </Pressable>
            ))}
          </View>
        </View>
      ))}
      <View style={s.add}>
        <TextInput style={s.input} value={draft} onChangeText={setDraft} placeholder="Add a goal" placeholderTextColor={C.muted}
          onSubmitEditing={() => {
            const t = draft.trim(); if (!t) return;
            setDraft("");
            save([...goals, { id: `g${Date.now()}`, title: t, category: "Custom", done: false }]);
          }} returnKeyType="done" />
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 16, paddingBottom: 24, gap: 14 },
  h1: { fontSize: 34, fontWeight: "700", color: C.text, marginVertical: 8 },
  group: { gap: 8 },
  cat: { fontSize: 13, fontWeight: "600", color: C.muted, marginLeft: 4 },
  card: { backgroundColor: C.surface, borderRadius: R.card, paddingHorizontal: 16 },
  row: { flexDirection: "row", alignItems: "center", gap: 14, paddingVertical: 14 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: C.border },
  box: { width: 24, height: 24, borderRadius: 7, borderWidth: 2, borderColor: "#9AA0AB", alignItems: "center", justifyContent: "center" },
  boxDone: { backgroundColor: C.accent, borderColor: C.accent },
  tick: { color: C.onAccent, fontSize: 14, fontWeight: "800" },
  title: { fontSize: 17, color: C.text },
  titleDone: { color: C.muted, textDecorationLine: "line-through" },
  plan: { fontSize: 14, color: C.muted },
  add: { backgroundColor: C.surface, borderRadius: R.card, paddingHorizontal: 16 },
  input: { fontSize: 17, color: C.text, paddingVertical: 14 },
});
