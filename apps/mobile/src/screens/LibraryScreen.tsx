// Library: everything the agent built for you, as attachment-style rows
// (icon, title, kind) matching the cards that appear in the chat.
import React, { useCallback, useEffect, useState } from "react";
import { FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { Pressable } from "../ui/Tap";
import { C, R } from "../theme";
import type { Api, FileEntry } from "../api";

function kind(path: string) {
  const ext = (path.split(".").pop() ?? "").toLowerCase();
  if (ext === "pdf") return { label: "PDF", icon: "📕" };
  if (["html", "htm"].includes(ext)) return { label: "Interactive", icon: "🧩" };
  if (["md", "txt"].includes(ext)) return { label: "Document", icon: "📄" };
  if (["csv", "xlsx"].includes(ext)) return { label: "Spreadsheet", icon: "📊" };
  if (["png", "jpg", "jpeg"].includes(ext)) return { label: "Image", icon: "🖼️" };
  return { label: ext.toUpperCase() || "File", icon: "📎" };
}

export function LibraryScreen({ api }: { api: Api }) {
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setFiles((await api.files()).files); } catch {}
    setRefreshing(false);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  return (
    <FlatList
      data={[...files].sort((a, b) => b.mtime - a.mtime)}
      keyExtractor={(f) => f.path}
      style={s.root}
      contentContainerStyle={s.list}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
      ListHeaderComponent={<Text style={s.h1}>Library</Text>}
      ListEmptyComponent={<Text style={s.empty}>Documents, PDFs, and interactive pages your agent makes will show up here.</Text>}
      renderItem={({ item }) => {
        const k = kind(item.path);
        const name = item.path.split("/").pop() ?? item.path;
        return (
          <Pressable style={s.row} onPress={() => WebBrowser.openBrowserAsync(api.fileUrl(item.path))}>
            <View style={s.icon}><Text style={{ fontSize: 24 }}>{k.icon}</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name} numberOfLines={1}>{name.replace(/\.[^.]+$/, "")}</Text>
              <Text style={s.meta}>{k.label}</Text>
            </View>
            <Text style={s.more}>···</Text>
          </Pressable>
        );
      }}
    />
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  list: { paddingHorizontal: 16, paddingBottom: 24, gap: 10 },
  h1: { fontSize: 34, fontWeight: "700", color: C.text, marginVertical: 8 },
  row: { flexDirection: "row", alignItems: "center", gap: 14, backgroundColor: C.bubbleAgent, borderRadius: R.card, padding: 14 },
  icon: { width: 48, height: 48, borderRadius: 12, backgroundColor: C.surface, alignItems: "center", justifyContent: "center" },
  name: { fontSize: 18, fontWeight: "600", color: C.text },
  meta: { fontSize: 15, color: C.muted, marginTop: 2 },
  more: { fontSize: 18, color: C.muted, letterSpacing: 1 },
  empty: { fontSize: 16, lineHeight: 23, color: C.muted, textAlign: "center", marginTop: 60, paddingHorizontal: 30 },
});
