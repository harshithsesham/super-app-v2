// The Secure Store card: the agent needs a sign-in, an API key, or a new password
// for a site. "Add" opens the secure entry page in the system browser sheet; what
// the user types goes to the cell's vault and never through the chat.
import React, { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { Ionicons } from "@expo/vector-icons";
import { Pressable } from "./Tap";
import { C, R } from "../theme";
import type { CredentialRequest } from "../api";

export function CredentialCard({ request, onDecline, onSaved }: { request: CredentialRequest; onDecline?: (id: string) => void; onSaved?: () => void }) {
  const [busy, setBusy] = useState(false);
  const title = request.kind === "api_key" ? `API access for ${request.provider ?? request.site}`
    : request.kind === "new_password" ? `New password for ${request.site}` : `Sign in to ${request.site}`;
  const add = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await WebBrowser.openAuthSessionAsync(request.entry_url, "superapp://credentials-saved");
      onSaved?.();
    } catch {} finally { setBusy(false); }
  };
  return (
    <View style={s.card}>
      <View style={s.head}>
        <View style={s.icon}><Ionicons name="shield-checkmark" size={22} color={C.text} /></View>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Secure Store</Text>
          <Text style={s.sub} numberOfLines={1}>{title}</Text>
        </View>
      </View>
      {request.status === "saved" ? (
        <View style={s.done}><Ionicons name="checkmark-circle" size={18} color={C.green} /><Text style={s.doneText}>Saved to your Secure Store</Text></View>
      ) : request.status === "declined" ? (
        <Text style={s.declined}>Declined</Text>
      ) : (
        <View style={s.actions}>
          <Pressable style={s.add} feel="control" onPress={add} disabled={busy}><Text style={s.addText}>{busy ? "Opening…" : "Add"}</Text></Pressable>
          {onDecline ? <Pressable style={s.no} feel="control" onPress={() => onDecline(request.id)}><Text style={s.noText}>Not now</Text></Pressable> : null}
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card: { backgroundColor: C.bubbleAgent, borderRadius: R.card, padding: 12, gap: 12, alignSelf: "stretch" },
  head: { flexDirection: "row", alignItems: "center", gap: 12 },
  icon: { width: 44, height: 44, borderRadius: 12, backgroundColor: C.surface, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 17, fontWeight: "600", color: C.text },
  sub: { fontSize: 15, color: C.muted, marginTop: 1 },
  actions: { flexDirection: "row", gap: 8 },
  add: { flex: 1, backgroundColor: C.surface, borderRadius: R.pill, paddingVertical: 14, alignItems: "center" },
  addText: { fontSize: 17, fontWeight: "600", color: C.text },
  no: { borderRadius: R.pill, paddingVertical: 14, paddingHorizontal: 18, alignItems: "center" },
  noText: { fontSize: 15, color: C.muted },
  done: { flexDirection: "row", alignItems: "center", gap: 8 },
  doneText: { fontSize: 15, color: C.green },
  declined: { fontSize: 15, color: C.muted },
});
