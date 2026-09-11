// The agent's avatar: the Neo orb from the voice dock, a lavender sphere with a
// soft glow, sized to fit the chat header, the sign-in screen, or a list row.
import React from "react";
import { StyleSheet, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";

export const ORB_COLORS = ["#DCD2FF", "#8F7CFF", "#4B3AA8"] as const;

export function Avatar({ size = 64 }: { size?: number }) {
  const r = size / 2;
  return (
    <View style={[s.wrap, { width: size, height: size, borderRadius: r, shadowRadius: size * 0.32 }]}>
      <LinearGradient colors={[...ORB_COLORS]} start={{ x: 0.2, y: 0.1 }} end={{ x: 0.9, y: 1 }}
        style={{ width: size, height: size, borderRadius: r, borderWidth: 1, borderColor: "rgba(199,184,255,0.4)" }} />
      <View style={[s.highlight, { width: size * 0.34, height: size * 0.22, borderRadius: size * 0.17, top: size * 0.14, left: size * 0.2 }]} />
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { shadowColor: "#9F8CFF", shadowOpacity: 0.9, shadowOffset: { width: 0, height: 0 }, elevation: 8 },
  highlight: { position: "absolute", backgroundColor: "rgba(255,255,255,0.28)" },
});
