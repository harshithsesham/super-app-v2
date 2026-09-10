// Tab bar and header glyphs, drawn with views so there is no icon font to
// ship. Chat, Feed, Ideas, Goals, Library, plus the hamburger and mic.
import React from "react";
import { StyleSheet, Text, View } from "react-native";
import { C } from "../theme";

const stroke = (active: boolean) => (active ? C.accent : C.muted);

export function ChatIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box]}>
      <View style={{ width: 22, height: 18, borderRadius: 11, borderWidth: 2, borderColor: c }} />
      <View style={{ position: "absolute", left: 4, bottom: -1, width: 7, height: 7, backgroundColor: C.panel, borderLeftWidth: 2, borderBottomWidth: 2, borderColor: c, transform: [{ rotate: "-20deg" }] }} />
    </View>
  );
}
export function FeedIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box, { width: 22, height: 20, borderRadius: 5, borderWidth: 2, borderColor: c, padding: 3, gap: 2 }]}>
      <View style={{ width: 6, height: 5, backgroundColor: c, borderRadius: 1 }} />
      <View style={{ height: 2, backgroundColor: c, width: 12 }} />
      <View style={{ height: 2, backgroundColor: c, width: 12 }} />
    </View>
  );
}
export function IdeasIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box, { alignItems: "center" }]}>
      <View style={{ width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: c }} />
      <View style={{ width: 8, height: 5, borderWidth: 2, borderTopWidth: 0, borderColor: c, marginTop: -1, borderBottomLeftRadius: 2, borderBottomRightRadius: 2 }} />
    </View>
  );
}
export function GoalsIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box, { width: 20, height: 20, borderRadius: 5, borderWidth: 2, borderColor: c, alignItems: "center", justifyContent: "center" }]}>
      <Text style={{ color: c, fontSize: 12, fontWeight: "800", lineHeight: 14 }}>✓</Text>
    </View>
  );
}
export function LibraryIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box, { width: 22, height: 22, flexDirection: "row", flexWrap: "wrap", gap: 3 }]}>
      <View style={{ width: 9, height: 9, borderRadius: 5, borderWidth: 2, borderColor: c }} />
      <View style={{ width: 0, height: 0, borderLeftWidth: 5, borderRightWidth: 5, borderBottomWidth: 9, borderLeftColor: "transparent", borderRightColor: "transparent", borderBottomColor: c }} />
      <View style={{ width: 9, height: 9, borderRadius: 2, borderWidth: 2, borderColor: c }} />
      <View style={{ width: 9, height: 9, borderRadius: 2, borderWidth: 2, borderColor: c, transform: [{ rotate: "45deg" }], marginLeft: 1 }} />
    </View>
  );
}
export function HubIcon({ active }: { active?: boolean }) {
  const c = stroke(!!active);
  return (
    <View style={[i.box, { width: 22, height: 22, flexDirection: "row", flexWrap: "wrap", gap: 4 }]}>
      {[0, 1, 2, 3].map((k) => <View key={k} style={{ width: 9, height: 9, borderRadius: 3, borderWidth: 2, borderColor: c }} />)}
    </View>
  );
}
export function MenuIcon() {
  return (
    <View style={{ gap: 5 }}>
      <View style={{ width: 18, height: 2, backgroundColor: C.text, borderRadius: 1 }} />
      <View style={{ width: 18, height: 2, backgroundColor: C.text, borderRadius: 1 }} />
    </View>
  );
}
export function MicIcon() {
  return (
    <View style={{ alignItems: "center" }}>
      <View style={{ width: 8, height: 13, borderRadius: 4, borderWidth: 2, borderColor: C.body }} />
      <View style={{ width: 14, height: 8, borderBottomLeftRadius: 7, borderBottomRightRadius: 7, borderWidth: 2, borderTopWidth: 0, borderColor: C.body, marginTop: -3 }} />
      <View style={{ width: 2, height: 3, backgroundColor: C.body }} />
    </View>
  );
}
export function BackIcon() {
  return <Text style={{ fontSize: 22, color: C.text, lineHeight: 24 }}>‹</Text>;
}

const i = StyleSheet.create({ box: { alignItems: "center", justifyContent: "center" } });
