// The approval card from the app: an icon and title line, a short reason,
// the details the user should verify, and Deny / Allow. Rendered outside
// the message list so the agent's own text can never imitate it.
import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { Pressable } from "./Tap";
import { C, R } from "../theme";
import type { Approval } from "../api";

const ICON: Record<string, string> = { gmail_send: "✉️", gmail_modify: "🏷️", gmail_delete: "🗑️", checkout: "🛒" };

export function ApprovalCard({ approval, onDecide, busy }: {
  approval: Approval; onDecide: (d: "allow" | "deny") => void; busy?: boolean;
}) {
  return (
    <View style={s.card}>
      <View style={s.head}>
        <View style={s.iconWrap}><Text style={{ fontSize: 20 }}>{ICON[approval.kind] ?? "🔒"}</Text></View>
        <Text style={s.title}>{approval.title}</Text>
      </View>
      {approval.subtitle ? <Text style={s.sub}>{approval.subtitle}</Text> : null}
      <View style={s.details}>
        {approval.details.map((d, i) => (
          <View key={i} style={[s.row, i < approval.details.length - 1 && s.rowBorder]}>
            <Text style={s.label}>{d.label}</Text>
            <Text style={s.value} numberOfLines={d.label === "Body" ? 8 : 2}>{d.value}</Text>
          </View>
        ))}
      </View>
      <View style={s.actions}>
        <Pressable style={s.deny} feel="control" disabled={busy} onPress={() => onDecide("deny")}>
          <Text style={s.denyText}>Deny</Text>
        </Pressable>
        <Pressable style={s.allow} feel="control" disabled={busy} onPress={() => onDecide("allow")}>
          <Text style={s.allowText}>Allow</Text>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: C.surface, borderRadius: R.card, padding: 16, gap: 12, marginHorizontal: 14, marginBottom: 8,
    shadowColor: "#000", shadowOpacity: 0.08, shadowRadius: 14, shadowOffset: { width: 0, height: 4 } },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  iconWrap: { width: 40, height: 40, borderRadius: 12, backgroundColor: C.blueTint, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, fontSize: 17, fontWeight: "600", color: C.text, lineHeight: 22 },
  sub: { fontSize: 15, color: C.muted, lineHeight: 21 },
  details: { backgroundColor: C.bg, borderRadius: 14, paddingHorizontal: 12 },
  row: { paddingVertical: 10, gap: 2 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: C.border },
  label: { fontSize: 12, color: C.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  value: { fontSize: 15, color: C.text, lineHeight: 20 },
  actions: { flexDirection: "row", gap: 10 },
  deny: { flex: 1, backgroundColor: C.card, borderRadius: R.pill, paddingVertical: 14, alignItems: "center" },
  denyText: { fontSize: 17, fontWeight: "600", color: C.text },
  allow: { flex: 1, backgroundColor: C.accent, borderRadius: R.pill, paddingVertical: 14, alignItems: "center" },
  allowText: { fontSize: 17, fontWeight: "600", color: C.onAccent },
});
