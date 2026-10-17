import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import * as contracts from "../src/index.js";

const outputDirectory = join(import.meta.dirname, "..", "schema");
// Compare stable content without rewriting files or consulting the Git index.
const schemas = Object.entries(contracts)
  .filter(
    ([name, value]) => name.endsWith("Schema") && value instanceof z.ZodType,
  )
  .sort(([left], [right]) => left.localeCompare(right));
const expected = new Map<string, string>();
for (const [name, schema] of schemas) {
  expected.set(
    `${name}.json`,
    `${JSON.stringify(
      {
        $id: `https://schemas.research.local/${contracts.SCHEMA_VERSION}/${name}.json`,
        title: name,
        ...z.toJSONSchema(schema as z.ZodType, {
          target: "draft-2020-12",
          unrepresentable: "any",
        }),
      },
      null,
      2,
    )}\n`,
  );
}
expected.set(
  "manifest.json",
  `${JSON.stringify(
    {
      schemaVersion: contracts.SCHEMA_VERSION,
      schemas: schemas.map(([name]) => name),
    },
    null,
    2,
  )}\n`,
);

const actualFiles = (await readdir(outputDirectory)).filter((file) =>
  file.endsWith(".json"),
);
const differences = actualFiles
  .filter((file) => !expected.has(file))
  .map((file) => `Unexpected: ${file}`);
for (const [file, content] of expected) {
  if (!actualFiles.includes(file)) differences.push(`Missing: ${file}`);
  else if ((await readFile(join(outputDirectory, file), "utf8")) !== content)
    differences.push(`Stale: ${file}`);
}
if (differences.length) {
  throw new Error(
    `Generated schemas differ; run corepack pnpm --filter @research/contracts generate.\n${differences.join("\n")}`,
  );
}

console.log(`Verified ${expected.size} generated JSON Schema documents.`);
