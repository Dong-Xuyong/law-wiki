import { defineConfig } from "astro/config";
import react from "@astrojs/react";

const base = process.env.BASE_PATH || "/law-wiki";

export default defineConfig({
  site: process.env.SITE_URL || "https://dong-xuyong.github.io",
  base,
  output: "static",
  integrations: [react()],
  build: { format: "directory" },
});
