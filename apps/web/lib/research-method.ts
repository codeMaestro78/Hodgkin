type MethodSource = {
  id: string;
  title: string;
  url: string;
  provider: string;
  discoveryPaths?: { subQuestionId: string; provider: string }[];
};
type MethodQuestion = { id: string; question: string; status: string };
export type ProviderCount = { id: string; label: string; count: number };

const LABELS: Record<string, string> = {
  tavily: "Tavily",
  exa: "Exa",
  brave: "Brave",
  serper: "Serper",
  firecrawl: "Firecrawl",
  openalex: "OpenAlex",
  semantic_scholar: "Semantic Scholar",
  semanticscholar: "Semantic Scholar",
  arxiv: "arXiv",
  crossref: "Crossref",
  pubmed: "PubMed",
  upload: "Upload",
  library: "Library",
};

export function providerLabel(id: string) {
  const key = id.trim().toLowerCase();
  if (LABELS[key]) return LABELS[key];
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Unknown";
}

function tally(entries: Map<string, Set<string>>): ProviderCount[] {
  return [...entries]
    .map(([id, ids]) => ({ id, label: providerLabel(id), count: ids.size }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

function add(map: Map<string, Set<string>>, key: string, value: string) {
  const set = map.get(key) ?? new Set<string>();
  set.add(value);
  map.set(key, set);
}

/** Counts unique sources, never discovery events, so repeated hits are not inflated. */
export function methodSummary(
  sources: MethodSource[],
  subQuestions: MethodQuestion[],
) {
  const overall = new Map<string, Set<string>>();
  const perQuestion = new Map<string, Map<string, Set<string>>>();
  const known = new Set(subQuestions.map((item) => item.id));
  let unattributed = 0;
  for (const source of sources) {
    const paths = source.discoveryPaths ?? [];
    const providers = paths.length
      ? paths.map((path) => path.provider)
      : [source.provider];
    for (const provider of providers)
      if (provider) add(overall, provider, source.id);
    let attributed = false;
    for (const path of paths) {
      if (!known.has(path.subQuestionId)) continue;
      attributed = true;
      const map = perQuestion.get(path.subQuestionId) ?? new Map();
      add(map, path.provider || source.provider, source.id);
      perQuestion.set(path.subQuestionId, map);
    }
    if (!attributed) unattributed += 1;
  }
  const byId = new Map(sources.map((source) => [source.id, source]));
  return {
    providers: tally(overall),
    unattributed,
    questions: subQuestions.map((item) => {
      const map = perQuestion.get(item.id) ?? new Map<string, Set<string>>();
      const ids = new Set([...map.values()].flatMap((set) => [...set]));
      return {
        ...item,
        providers: tally(map),
        sources: [...ids].flatMap((id) => byId.get(id) ?? []),
      };
    }),
  };
}
