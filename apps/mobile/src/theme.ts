// The space theme carried over from the Nano app: near-black ground with
// faint stars, lavender accent, mint for "good", serif headlines, mono for
// stamps and labels. Muse's structure underneath: thread, avatar, cards, tabs.
export const C = {
  bg: "#08070E",
  panel: "#0B0A14",
  surface: "#14101F",
  card: "#1A1628",
  bubbleAgent: "#1B1828",
  bubbleUser: "rgba(199,184,255,0.22)",
  border: "rgba(199,184,255,0.14)",
  text: "#F4F2FA",
  body: "#B9B4CC",
  muted: "#8A87A3",
  accent: "#C7B8FF",
  accentDeep: "#6D5BD0",
  onAccent: "#14101F",
  blueTint: "rgba(199,184,255,0.14)",
  green: "#7CF7C4",
  red: "#FF9DA8",
  amber: "#FBBF24",
  avatar: "#EADFD0",
  avatarShade: "#D9C7B3",
} as const;

export const F = {
  serif: "InstrumentSerif_400Regular",
  sans: "InstrumentSans_400Regular",
  sansSemi: "InstrumentSans_600SemiBold",
  mono: "JetBrainsMono_400Regular",
} as const;

export const R = { bubble: 22, card: 20, pill: 28 } as const;
