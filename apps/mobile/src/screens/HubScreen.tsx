// My Hub, as it was: serif title, the lavender briefing card with Play, the
// Inbox Zero card with stat tiles, and the grid. Everything on it now comes
// from the agent: its latest brief, the Gmail connector, goals, and skills.
import { LinearGradient } from "expo-linear-gradient";
import React, { useCallback, useEffect, useState } from "react";
import { RefreshControl, ScrollView, StyleSheet, Text, View } from "react-native";
import { Pressable } from "../ui/Tap";
import { C, F } from "../theme";
import type { Api, Hub } from "../api";

const STAT_COLORS = ["#7CF7C4", "#C7B8FF", "#F4F2FA"];
const GRADS: Record<string, [string, string]> = {
  mint: ["#4ADE80", "#15803D"], amber: ["#FBBF24", "#B45309"], rose: ["#F87171", "#B91C1C"], indigo: ["#818CF8", "#4338CA"],
};

export function HubScreen({ api, assistant, onAsk, onPlay, onConnect }: {
  api: Api; assistant: string; onAsk: (text: string) => void; onPlay: (text: string) => void; onConnect: () => void;
}) {
  const [hub, setHub] = useState<Hub | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setHub(await api.hub()); } catch {}
    setRefreshing(false);
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const initial = (assistant || "M").slice(0, 1).toUpperCase();
  return (
    <ScrollView contentContainerStyle={s.root}
      refreshControl={<RefreshControl refreshing={refreshing} tintColor={C.accent} onRefresh={() => { setRefreshing(true); load(); }} />}>
      <View style={s.topRow}>
        <Text style={s.stamp}>{hub?.stamp ?? ""}</Text>
        <Pressable onPress={onConnect} hitSlop={10}>
          <View style={s.avatarWrap}>
            <LinearGradient colors={["#C7B8FF", "#6D5BD0"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.avatarChip}>
              <Text style={s.avatarChipText}>{initial}</Text>
            </LinearGradient>
            <View style={s.avatarDot} />
          </View>
        </Pressable>
      </View>
      <Text style={s.title}>My Hub</Text>
      <Text style={s.hint}>{hub?.greeting ?? ""} Tap the orb to talk.</Text>

      <Pressable onPress={() => hub?.brief.text ? onPlay(hub.brief.text) : onAsk("Give me my morning brief.")}>
        <LinearGradient colors={["rgba(139,123,240,0.9)", "rgba(58,44,110,0.92)"]} start={{ x: 0.1, y: 0 }} end={{ x: 0.9, y: 1 }} style={s.briefing}>
          <View style={s.briefGlow} pointerEvents="none" />
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <View style={s.readyDot} />
            <Text style={s.readyText}>{hub?.brief.ready ? "READY FOR YOU" : "COMING SOON"}</Text>
          </View>
          <Text style={s.briefTitle}>{hub?.brief.title ?? "Morning briefing"}</Text>
          <Text style={s.briefSub}>{hub?.brief.sub ?? "Your day, in forty seconds. Read it or let me say it."}</Text>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 9, marginTop: 15 }}>
            <View style={s.playPill}><Text style={s.playText}>{hub?.brief.ready ? "Play" : "Ask"}</Text></View>
            <Text style={s.playMeta}>{(hub?.brief.kicker ?? "DAILY").toUpperCase()}</Text>
          </View>
        </LinearGradient>
      </Pressable>

      <Pressable onPress={() => hub?.inbox.connected ? onAsk("Summarise my inbox and tell me what needs me.") : onConnect()}>
        <LinearGradient colors={["rgba(129,140,248,0.30)", "rgba(67,56,202,0.16)"]} start={{ x: 0.1, y: 0 }} end={{ x: 0.9, y: 1 }} style={s.inboxCard}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 11 }}>
            <LinearGradient colors={GRADS.indigo} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.inboxTile}>
              <Text style={s.inboxTileText}>I</Text>
            </LinearGradient>
            <View style={{ flex: 1 }}>
              <Text style={s.inboxName}>Inbox Zero</Text>
              <Text style={s.inboxSub}>{hub?.inbox.connected ? hub.inbox.email ?? "Gmail" : "Not connected"}</Text>
            </View>
            {hub?.inbox.connected ? <Text style={s.live}>LIVE</Text> : null}
            <Text style={s.chevron}>›</Text>
          </View>
          <Text style={s.inboxHeadline}>{hub?.inbox.headline ?? "…"}</Text>
          <Text style={s.inboxBody}>{hub?.inbox.body ?? ""}</Text>
          {hub?.inbox.stats?.length ? (
            <View style={{ flexDirection: "row", gap: 8, marginTop: 15 }}>
              {hub.inbox.stats.map((st, i) => (
                <View key={i} style={s.statTile}>
                  <Text style={[s.statN, { color: STAT_COLORS[i] ?? C.text }]}>{st.n}</Text>
                  <Text style={s.statLabel}>{st.label}</Text>
                </View>
              ))}
              <View style={s.statTile}>
                <Text style={[s.statN, { color: STAT_COLORS[2] }]}>{hub?.goals.open ?? 0}</Text>
                <Text style={s.statLabel}>open goals</Text>
              </View>
            </View>
          ) : null}
        </LinearGradient>
      </Pressable>

      <Text style={s.sectionTitle}>Your Hub</Text>
      <View style={s.cards}>
        {(hub?.grid ?? []).map((g) => (
          <Pressable key={g.name} style={s.card} onPress={() => (g.status === "connected" ? onAsk(g.ask) : onConnect())}>
            <LinearGradient colors={GRADS[g.tone] ?? GRADS.indigo} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={s.cardTile}>
              <Text style={s.cardTileText}>{g.name[0]}</Text>
            </LinearGradient>
            <Text style={s.cardName}>{g.name}</Text>
            <Text style={s.cardSub} numberOfLines={1}>{g.sub}</Text>
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  root: { paddingHorizontal: 20, paddingBottom: 40 },
  topRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stamp: { fontFamily: F.mono, fontSize: 11, letterSpacing: 3, color: C.muted, marginTop: 8 },
  avatarWrap: { width: 40, height: 40 },
  avatarChip: { width: 38, height: 38, borderRadius: 19, alignItems: "center", justifyContent: "center" },
  avatarChipText: { fontFamily: F.sansSemi, fontSize: 15, color: "#14101F" },
  avatarDot: { position: "absolute", right: 0, bottom: 0, width: 10, height: 10, borderRadius: 5, backgroundColor: C.green, borderWidth: 2, borderColor: "#0B0910" },
  title: { fontFamily: F.serif, fontSize: 42, lineHeight: 48, color: C.text, marginTop: 6 },
  hint: { fontFamily: F.sans, fontSize: 13, color: C.accent, marginTop: 8 },
  briefing: { marginTop: 20, padding: 18, borderRadius: 24, overflow: "hidden", borderWidth: 1, borderColor: "rgba(199,184,255,0.3)" },
  briefGlow: { position: "absolute", right: -40, bottom: -52, width: 170, height: 170, borderRadius: 85, backgroundColor: "rgba(255,255,255,0.13)" },
  readyDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: C.green, shadowColor: C.green, shadowOpacity: 1, shadowRadius: 8, shadowOffset: { width: 0, height: 0 } },
  readyText: { fontFamily: F.mono, fontSize: 10.5, letterSpacing: 2.5, color: "rgba(255,255,255,0.78)" },
  briefTitle: { fontFamily: F.serif, fontSize: 27, lineHeight: 30, color: "#FFFFFF", marginTop: 9 },
  briefSub: { fontFamily: F.sans, fontSize: 13, lineHeight: 19.5, color: "rgba(255,255,255,0.72)", marginTop: 6 },
  playPill: { paddingHorizontal: 15, paddingVertical: 9, borderRadius: 100, backgroundColor: "rgba(255,255,255,0.16)", borderWidth: 1, borderColor: "rgba(255,255,255,0.24)" },
  playText: { fontFamily: F.sansSemi, fontSize: 12.5, color: "#FFFFFF" },
  playMeta: { fontFamily: F.mono, fontSize: 10, letterSpacing: 1.5, color: "rgba(255,255,255,0.6)" },
  inboxCard: { marginTop: 12, padding: 17, borderRadius: 24, borderWidth: 1, borderColor: "rgba(199,184,255,0.26)" },
  inboxTile: { width: 44, height: 44, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  inboxTileText: { fontFamily: F.sansSemi, fontSize: 17, color: "#FFFFFF" },
  inboxName: { fontFamily: F.sansSemi, fontSize: 15, color: C.text },
  inboxSub: { fontFamily: F.sans, fontSize: 11.5, color: "rgba(244,242,250,0.6)", marginTop: 2 },
  live: { fontFamily: F.mono, fontSize: 10.5, letterSpacing: 1.5, color: "rgba(124,247,196,0.9)" },
  chevron: { color: "rgba(244,242,250,0.5)", fontSize: 20, lineHeight: 22, marginLeft: 2 },
  inboxHeadline: { fontFamily: F.serif, fontSize: 25, lineHeight: 28.5, color: C.text, marginTop: 14 },
  inboxBody: { fontFamily: F.sans, fontSize: 13, lineHeight: 19.5, color: "rgba(244,242,250,0.66)", marginTop: 7 },
  statTile: { flex: 1, paddingHorizontal: 12, paddingVertical: 11, borderRadius: 15, backgroundColor: "rgba(0,0,0,0.22)", borderWidth: 1, borderColor: "rgba(255,255,255,0.09)" },
  statN: { fontFamily: F.serif, fontSize: 22, lineHeight: 23 },
  statLabel: { fontFamily: F.sans, fontSize: 10.5, lineHeight: 14, color: "rgba(244,242,250,0.62)", marginTop: 5 },
  sectionTitle: { fontFamily: F.sansSemi, fontSize: 16, color: C.text, marginTop: 28, marginBottom: 11 },
  cards: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  card: { width: "48.4%", padding: 14, borderRadius: 20, backgroundColor: "rgba(255,255,255,0.025)", borderWidth: 1, borderColor: "rgba(255,255,255,0.12)" },
  cardTile: { width: 28, height: 28, borderRadius: 9, alignItems: "center", justifyContent: "center" },
  cardTileText: { fontFamily: F.sansSemi, fontSize: 11, color: "#FFFFFF" },
  cardName: { fontFamily: F.sansSemi, fontSize: 12.5, color: "rgba(244,242,250,0.9)", marginTop: 10 },
  cardSub: { fontFamily: F.mono, fontSize: 9.5, letterSpacing: 1, color: "rgba(244,242,250,0.42)", marginTop: 4 },
});
