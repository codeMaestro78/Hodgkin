import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import * as contracts from "../src/index.js";

const outputDirectory = join(import.meta.dirname, "..", "schema");
await mkdir(outputDirectory, { recursive: true });

const schemas = Object.entries(contracts)
  .filter(
    ([name, value]) => name.endsWith("Schema") && value instanceof z.ZodType,
  )
  .sort(([left], [right]) => left.localeCompare(right));

for (const [name, schema] of schemas) {
  const jsonSchema = z.toJSONSchema(schema as z.ZodType, {
    target: "draft-2020-12",
    unrepresentable: "any",
  });
  const document = {
    $id: `https://schemas.research.local/${contracts.SCHEMA_VERSION}/${name}.json`,
    title: name,
    ...jsonSchema,
  };
  await writeFile(
    join(outputDirectory, `${name}.json`),
    `${JSON.stringify(document, null, 2)}\n`,
  );
}

await writeFile(
  join(outputDirectory, "manifest.json"),
  `${JSON.stringify({ schemaVersion: contracts.SCHEMA_VERSION, schemas: schemas.map(([name]) => name) }, null, 2)}\n`,
);
