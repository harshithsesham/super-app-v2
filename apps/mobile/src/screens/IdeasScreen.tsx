// Ideas: things the agent proposes to take on. Rows of icon, bold title,
// and a gray explanation; tapping one starts it in the Main chat.
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { C } from "../theme";
import type { Api, Idea } from "../api";

export function IdeasScreen({ api, onStart }: { api: Api; onStart: (idea: Idea) => void }) {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setIdeas((await api.ideas()).ideas); } catch {}
    setRefreshing(false);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  return (
    <FlatList
      data={ideas}
      keyExtractor={(i) => i.id}
      style={s.root}
      contentContainerStyle={s.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      ListHeaderComponent={<Text style={s.h1}>Ideas</Text>}
      ItemSeparatorComponent={() => <View style={s.sep} />}
      renderItem={({ item }) => (
        <Pressable style={s.row} onPress={() => onStart(item)}>
          <Text style={s.icon}>{item.icon}</Text>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={s.title}>{item.title}</Text>
            <Text style={s.body}>{item.body}</Text>
          </View>
        </Pressable>
      )}
    />
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 16, paddingBottom: 24 },
  h1: { fontSize: 34, fontWeight: "700", color: C.text, marginVertical: 8 },
  row: { flexDirection: "row", gap: 16, paddingVertical: 18 },
  sep: { height: 1, backgroundColor: C.border },
  icon: { fontSize: 34, width: 44, textAlign: "center" },
  title: { fontSize: 19, fontWeight: "600", color: C.text, lineHeight: 25 },
  body: { fontSize: 16, lineHeight: 23, color: C.muted },
});
