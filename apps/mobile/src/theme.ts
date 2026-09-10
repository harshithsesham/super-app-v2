// Muse's visual language, taken from the shipped app: a light, near-white
// ground, iMessage-style bubbles (gray for the agent, pale blue for you),
// big rounded corners, a single blue accent, and the system sans.
export const C = {
  bg: "#F4F5F7",
  surface: "#FFFFFF",
  bubbleAgent: "#E8E9ED",
  bubbleUser: "#CFE3FF",
  card: "#ECEDF0",
  border: "#E3E4E8",
  text: "#111318",
  body: "#3A3D45",
  muted: "#7A7E88",
  accent: "#2B6BFF",
  accentDeep: "#1E4FD6",
  blueTint: "#E6F0FF",
  green: "#22C55E",
  red: "#E5484D",
  amber: "#F59E0B",
  avatar: "#EADFD0",
  avatarShade: "#D9C7B3",
} as const;

export const R = { bubble: 22, card: 20, pill: 28 } as const;
