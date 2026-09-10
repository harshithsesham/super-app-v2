// A Pressable with press feedback baked in (RN's renders none of its own).
// "card" for cards, tiles and rows; "control" for pills, buttons and icons.
import React from "react";
import { Pressable as RNPressable } from "react-native";
import type { PressableProps, StyleProp, ViewStyle } from "react-native";

type StyleArg = { pressed: boolean };
type PressStyle = StyleProp<ViewStyle> | ((state: StyleArg) => StyleProp<ViewStyle>);

const FEEDBACK = {
  card: { opacity: 0.82, transform: [{ scale: 0.985 }] },
  control: { opacity: 0.68, transform: [{ scale: 0.96 }] },
} as const;

export type TapProps = Omit<PressableProps, "style"> & {
  style?: PressStyle;
  feel?: keyof typeof FEEDBACK;
};

export function Pressable({ style, feel = "card", disabled, ...rest }: TapProps) {
  const resolve = React.useCallback(
    (state: StyleArg) => {
      const base = typeof style === "function" ? style(state) : style;
      if (!state.pressed || disabled) return base;
      return [base, FEEDBACK[feel]] as StyleProp<ViewStyle>;
    },
    [style, feel, disabled],
  );
  return <RNPressable style={resolve} disabled={disabled} {...rest} />;
}

export default Pressable;
