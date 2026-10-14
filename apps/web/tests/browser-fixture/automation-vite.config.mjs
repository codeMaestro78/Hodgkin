import { fileURLToPath } from "node:url";

export default {
  root: fileURLToPath(new URL(".", import.meta.url)),
  resolve: {
    alias: {
      "next/navigation": fileURLToPath(
        new URL("navigation.tsx", import.meta.url),
      ),
      "next/link": fileURLToPath(new URL("navigation.tsx", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 3102,
    strictPort: true,
    fs: { allow: [fileURLToPath(new URL("../../../../..", import.meta.url))] },
  },
};
