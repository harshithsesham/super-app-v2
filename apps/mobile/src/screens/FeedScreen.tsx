// Feed: short editorial posts the agent writes in the background. A new
// reader starts with the "Getting started" intro posts, as in the app.
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { C, R } from "../theme";
import type { Api, FeedPost } from "../api";

export function FeedScreen({ api, onDiscuss }: { api: Api; onDiscuss: (post: FeedPost) => void }) {
  const [posts, setPosts] = useState<FeedPost[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setPosts((await api.feed()).posts); } catch {}
    setRefreshing(false);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  return (
    <FlatList
      data={posts}
      keyExtractor={(p) => p.id}
      style={s.root}
      contentContainerStyle={s.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      ListHeaderComponent={<Text style={s.h1}>Feed</Text>}
      renderItem={({ item }) => (
        <View style={s.card}>
          <Text style={s.kicker}>{item.kicker.toUpperCase()} · {item.category.toUpperCase()}</Text>
          <Text style={s.title}>{item.title}</Text>
          <Text style={s.body}>{item.body}</Text>
          <Pressable style={s.discuss} feel="control" onPress={() => onDiscuss(item)}>
            <Text style={s.discussText}>Discuss</Text>
          </Pressable>
        </View>
      )}
    />
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 16, paddingBottom: 24, gap: 12 },
  h1: { fontSize: 34, fontWeight: "700", color: C.text, marginVertical: 8 },
  card: { backgroundColor: C.surface, borderRadius: R.card, padding: 18, gap: 8 },
  kicker: { fontSize: 11, letterSpacing: 1, color: C.accent, fontWeight: "600" },
  title: { fontSize: 20, fontWeight: "600", color: C.text, lineHeight: 26 },
  body: { fontSize: 16, lineHeight: 23, color: C.body },
  discuss: { alignSelf: "flex-start", backgroundColor: C.card, borderRadius: 16, paddingHorizontal: 14, paddingVertical: 8, marginTop: 4 },
  discussText: { fontSize: 15, fontWeight: "600", color: C.text },
});
