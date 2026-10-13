import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import "./generate-json-schema.js";

const outputDirectory = join(import.meta.dirname, "..", "schema");
const files = (await readdir(outputDirectory)).filter((file) =>
  file.endsWith(".json"),
);

for (const file of files) {
  JSON.parse(await readFile(join(outputDirectory, file), "utf8"));
}

console.log(`Validated ${files.length} generated JSON Schema documents.`);
