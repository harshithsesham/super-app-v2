// Connectors: the settings page from the app, with a search field and
// Connected / Available sections. Rows come from the skills registry.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { Pressable } from "../ui/Tap";
import { BackIcon } from "../ui/Icons";
import { C, R } from "../theme";
import type { SavedSite, Api, Connector, Skill } from "../api";

// Providers with a real connect flow in the daemon today. Gmail and Google Calendar
// share one Google sign-in; connecting either runs the same consent.
const LIVE: Record<string, string> = { gmail: "gmail", "google-calendar": "google_calendar" };

const PRETTY: Record<string, string> = {
  gmail: "Gmail", "google-calendar": "Google Calendar", "google-contacts": "Google Contacts", "google-drive": "Google Drive",
  "google-docs": "Google Docs", "google-sheets": "Google Sheets", "google-slides": "Google Slides", "google-tasks": "Google Tasks",
  "google-forms": "Google Forms", healthex: "HealthEx", opentable: "OpenTable", "facebook-cli": "Facebook", instagram: "Instagram",
  "instagram-messages": "Instagram Messages", peloton: "Peloton", plaid: "Finances (Plaid)", "function-health": "Function Health",
  "outlook-mail": "Outlook Mail", "outlook-calendar": "Outlook Calendar", "outlook-contacts": "Outlook Contacts",
  spotify: "Spotify", tessie: "Tessie", withings: "Withings", "philips-hue": "Philips Hue", printify: "Printify",
  ticketmaster: "Ticketmaster", duffel: "Flights (Duffel)", flightaware: "FlightAware", calendly: "Calendly",
  messenger: "Messenger", threads: "Threads", "threads-messages": "Threads Messages", "apple-healthkit": "Apple Health",
  "google-health-connect": "Health Connect",
};
const CONNECTOR_SKILLS = new Set(Object.keys(PRETTY));

export function ConnectorsScreen({ api, onBack, onOpenBrowser }: { api: Api; onBack: () => void; onOpenBrowser?: () => void }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [sites, setSites] = useState<SavedSite[]>([]);
  const [live, setLive] = useState<Connector[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [sk, co] = await Promise.all([api.skills(), api.connectors()]);
      setSkills(sk.skills); setLive(co.connectors);
      api.browserLogins().then((r) => setSites(r.sites)).catch(() => {});
    } catch {}
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const connect = useCallback(async (name: string) => {
    if (busy) return;
    const provider = LIVE[name];
    if (!provider) { Alert.alert("Coming soon", "This connector is not wired up yet."); return; }
    setBusy(true);
    try {
      const { auth_url } = await api.gmailAuthUrl();
      const res = await WebBrowser.openAuthSessionAsync(auth_url, "superapp://gmail-connected");   // one consent covers Gmail + Calendar
      if (res.type !== "success" && res.type !== "cancel" && res.type !== "dismiss") throw new Error("Sign-in did not complete");
      await load();
    } catch (e) {
      Alert.alert("Couldn't connect", e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }, [api, busy, load]);

  const disconnect = useCallback((name: string) => {
    Alert.alert(`Disconnect ${PRETTY[name] ?? name}?`, "The saved sign-in will be removed.", [
      { text: "Cancel", style: "cancel" },
      { text: "Disconnect", style: "destructive", onPress: async () => { try { await api.gmailDisconnect(); await load(); } catch {} } },
    ]);
  }, [api, load]);

  const rows = useMemo(() => skills
    .filter((s) => CONNECTOR_SKILLS.has(s.name))
    .map((s) => ({ ...s, label: PRETTY[s.name] ?? s.name }))
    .filter((s) => s.label.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => a.label.localeCompare(b.label)), [skills, q]);
  const connected = rows.filter((r) => r.status === "connected");
  const available = rows.filter((r) => r.status !== "connected");

  const emailFor = (name: string) => live.find((c) => c.provider === LIVE[name])?.email ?? null;
  const Row = ({ r, last, action }: { r: (typeof rows)[number]; last: boolean; action?: string }) => (
    <Pressable style={[s.row, !last && s.rowBorder]} onPress={() => (action ? connect(r.name) : disconnect(r.name))}>
      <View style={s.logo}><Text style={s.logoText}>{r.label.slice(0, 1)}</Text></View>
      <View style={{ flex: 1 }}>
        <Text style={s.name}>{r.label}</Text>
        {!action && emailFor(r.name) ? <Text style={s.email}>{emailFor(r.name)}</Text> : null}
      </View>
      {action ? <Text style={s.connect}>{busy && LIVE[r.name] ? "…" : action}</Text> : <Text style={s.chev}>›</Text>}
    </Pressable>
  );

  return (
    <View style={s.root}>
      <View style={s.header}>
        <Pressable style={s.back} feel="control" onPress={onBack}><BackIcon /></Pressable>
        <Text style={s.title}>Connectors</Text>
        <View style={{ width: 44 }} />
      </View>
      <ScrollView contentContainerStyle={s.list}>
        <View style={s.search}>
          <Text style={{ fontSize: 16, color: C.muted }}>⌕</Text>
          <TextInput style={s.searchInput} value={q} onChangeText={setQ} placeholder="Search connectors" placeholderTextColor={C.muted} />
        </View>
        <Text style={s.section}>Browser</Text>
        <View style={s.card}>
          <View style={[s.row, s.rowBorder]}>
            <View style={s.logo}><Text style={{ fontSize: 20 }}>🌐</Text></View>
            <View style={{ flex: 1 }}>
              <Text style={s.name}>Muse's browser</Text>
              <Text style={s.email}>Sign into sites here once; it stays signed in for tasks.</Text>
            </View>
            <Pressable feel="control" onPress={onOpenBrowser}><Text style={s.connect}>Open</Text></Pressable>
          </View>
          {sites.length ? sites.slice(0, 12).map((site, i) => (
            <View key={site.site} style={[s.row, i < Math.min(sites.length, 12) - 1 && s.rowBorder]}>
              <View style={{ flex: 1 }}>
                <Text style={s.name}>{site.site}</Text>
                <Text style={s.email}>{site.cookies} cookie{site.cookies === 1 ? "" : "s"}{site.last_used_at ? ` · used ${new Date(site.last_used_at * 1000).toLocaleDateString()}` : ""}</Text>
              </View>
              <Pressable feel="control" onPress={() => Alert.alert(`Forget ${site.site}?`, "Muse's browser will be signed out of this site.", [
                { text: "Cancel", style: "cancel" },
                { text: "Forget", style: "destructive", onPress: async () => { try { const r = await api.browserForget(site.site); setSites(r.sites); } catch {} } },
              ])}><Text style={s.connect}>Forget</Text></Pressable>
            </View>
          )) : <Text style={s.none}>No saved sign-ins yet.</Text>}
        </View>
        <Text style={s.section}>Connected</Text>
        <View style={s.card}>
          {connected.length ? connected.map((r, i) => <Row key={r.name} r={r} last={i === connected.length - 1} />)
            : <Text style={s.none}>Nothing connected yet.</Text>}
        </View>
        <Text style={s.section}>Available</Text>
        <View style={s.card}>
          {available.map((r, i) => <Row key={r.name} r={r} last={i === available.length - 1} action="Connect" />)}
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8 },
  back: { width: 44, height: 44, borderRadius: 22, backgroundColor: C.surface, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 20, fontWeight: "600", color: C.text },
  list: { paddingHorizontal: 16, paddingBottom: 60, gap: 10 },
  search: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: C.surface, borderRadius: R.pill, paddingHorizontal: 16, height: 50 },
  searchInput: { flex: 1, fontSize: 17, color: C.text },
  section: { fontSize: 15, color: C.muted, marginTop: 10, marginLeft: 4 },
  card: { backgroundColor: C.surface, borderRadius: R.card, paddingHorizontal: 14 },
  row: { flexDirection: "row", alignItems: "center", gap: 14, paddingVertical: 14 },
  rowBorder: { borderBottomWidth: 1, borderBottomColor: C.border },
  logo: { width: 36, height: 36, borderRadius: 9, backgroundColor: C.blueTint, alignItems: "center", justifyContent: "center" },
  logoText: { fontSize: 16, fontWeight: "700", color: C.accent },
  name: { fontSize: 17, color: C.text },
  email: { fontSize: 13, color: C.muted, marginTop: 1 },
  connect: { fontSize: 17, fontWeight: "600", color: C.accent },
  chev: { fontSize: 22, color: C.muted },
  none: { fontSize: 16, color: C.muted, paddingVertical: 14 },
});
