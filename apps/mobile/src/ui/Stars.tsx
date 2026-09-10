// The faint starfield behind every screen, same constellation as the old app.
import React from "react";
import { StyleSheet, View } from "react-native";

const STARS = Array.from({ length: 26 }, (_, i) => ({
  left: (i * 137) % 100,
  top: (i * 89 + 13) % 100,
  size: 1 + (i % 3 === 0 ? 1 : 0),
  opacity: 0.12 + ((i * 31) % 36) / 100,
}));

export function Stars() {
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {STARS.map((st, i) => (
        <View key={i} style={{
          position: "absolute", left: `${st.left}%`, top: `${st.top}%`,
          width: st.size, height: st.size, borderRadius: 1, backgroundColor: "#CDBFFF", opacity: st.opacity,
        }} />
      ))}
    </View>
  );
}
