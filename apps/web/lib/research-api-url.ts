/** Build a path under a bound API base URL without discarding an optional base path. */
export function researchApiUrl(apiUrl: string, path: string): URL {
  const base = `${apiUrl.replace(/\/+$/, "")}/`;
  return new URL(path.replace(/^\/+/, ""), base);
}
