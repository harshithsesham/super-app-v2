// Sign in with Google, as the previous build did: the daemon runs the OAuth
// dance and bounces back through superapp://signed-in with a session token.
// In development builds only, a "Choose server" toggle keeps the app pointable at localhost,
// where a pasted token still works.
import React, { useCallback, useState } from "react";
import { StyleSheet, Text, TextInput, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { SafeAreaView } from "react-native-safe-area-context";
import { Pressable } from "../ui/Tap";
import { Avatar } from "../ui/Avatar";
import { C, R } from "../theme";
import { saveSession, type Session } from "../api";

export function SignInScreen({ defaultUrl, defaultToken, onSignedIn }: {
  defaultUrl: string; defaultToken?: string; onSignedIn: (s: Session) => void;
}) {
  const [url, setUrl] = useState(defaultUrl);
  const [token, setToken] = useState(defaultToken ?? "");
  const [advanced, setAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const server = () => url.trim().replace(/\/$/, "");

  const finish = useCallback(async (sess: Session) => {
    await saveSession(sess);
    onSignedIn(sess);
  }, [onSignedIn]);

  const google = useCallback(async () => {
    if (!server() || busy) return;
    setBusy(true); setError(null);
    try {
      const res = await WebBrowser.openAuthSessionAsync(`${server()}/v1/auth/google/start`, "superapp://signed-in");
      if (res.type !== "success" || !res.url) {
        if (res.type === "cancel" || res.type === "dismiss") return;
        throw new Error("Sign-in did not complete");
      }
      const params: Record<string, string> = {};
      for (const pair of (res.url.split("?")[1] ?? "").split("&")) {
        const [k, v] = pair.split("=");
        if (k) params[k] = decodeURIComponent(v ?? "");
      }
      if (!params.token) throw new Error("No session returned");
      await finish({ url: server(), token: params.token, user: params.user, name: params.name });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }, [url, busy, finish]);

  const withToken = useCallback(async () => {
    if (!server() || !token.trim() || busy) return;
    setBusy(true); setError(null);
    try {
      const res = await fetch(`${server()}/v1/me`, { headers: { Authorization: `Bearer ${token.trim()}` } });
      if (res.status === 401) throw new Error("That token was not accepted.");
      if (!res.ok) throw new Error(`Couldn't reach the server (${res.status}).`);
      const me = (await res.json()) as { user: string; name?: string };
      await finish({ url: server(), token: token.trim(), user: me.user, name: me.name });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }, [url, token, busy, finish]);

  return (
    <SafeAreaView style={s.root}>
      <View style={s.body}>
        <View style={{ alignItems: "center", marginBottom: 8 }}><Avatar size={96} /></View>
        <Text style={s.title}>Your personal agent that takes things off your plate</Text>
        <Text style={s.sub}>It has its own computer, memory, and browser. It works for you alone, and asks before anything gets sent or spent.</Text>
        {error ? <Text style={s.error}>{error}</Text> : null}
        <Pressable style={s.btn} feel="control" onPress={google} disabled={busy}>
          <Text style={s.btnText}>{busy ? "Signing in…" : "Continue with Google"}</Text>
        </Pressable>
        {__DEV__ ? (
          <>
            <Pressable onPress={() => setAdvanced((v) => !v)} feel="control">
              <Text style={s.advanced}>{advanced ? "Hide server" : "Choose server (dev)"}</Text>
            </Pressable>
            {advanced ? (
              <>
                <TextInput style={s.input} value={url} onChangeText={setUrl} autoCapitalize="none" autoCorrect={false} keyboardType="url"
                  placeholder="https://your-server" placeholderTextColor={C.muted} />
                <TextInput style={s.input} value={token} onChangeText={setToken} autoCapitalize="none" autoCorrect={false} secureTextEntry
                  placeholder="Access token (dev)" placeholderTextColor={C.muted} />
                <Pressable style={s.btnSecondary} feel="control" onPress={withToken} disabled={busy}>
                  <Text style={s.btnSecondaryText}>Continue with token</Text>
                </Pressable>
              </>
            ) : null}
          </>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  body: { flex: 1, justifyContent: "center", padding: 28, gap: 14 },
  title: { fontSize: 30, lineHeight: 36, fontWeight: "700", color: C.text, textAlign: "center" },
  sub: { fontSize: 16, lineHeight: 23, color: C.body, textAlign: "center", marginBottom: 10 },
  error: { color: C.red, fontSize: 14, textAlign: "center" },
  input: { backgroundColor: C.surface, borderRadius: 14, padding: 14, fontSize: 16, color: C.text },
  btn: { backgroundColor: C.accent, borderRadius: R.pill, paddingVertical: 16, alignItems: "center", marginTop: 6 },
  btnText: { fontSize: 17, fontWeight: "600", color: C.onAccent },
  btnSecondary: { backgroundColor: C.card, borderRadius: R.pill, paddingVertical: 14, alignItems: "center" },
  btnSecondaryText: { fontSize: 16, fontWeight: "600", color: C.text },
  advanced: { fontSize: 13, color: C.muted, textAlign: "center", marginTop: 4 },
});
