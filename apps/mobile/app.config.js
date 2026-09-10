// Overlays app.json at `expo start` time so the dev token and server URL come
// from the environment and never land in git.
export default ({ config }) => ({
  ...config,
  extra: {
    ...config.extra,
    apiUrl: process.env.SUPERAPP_API_URL ?? config.extra.apiUrl,
    apiToken: process.env.SUPERAPP_API_TOKEN ?? config.extra.apiToken,
  },
});
