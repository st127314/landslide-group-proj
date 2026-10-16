import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Self-contained server bundle (.next/standalone) so the Docker image stays small.
  output: "standalone",
  /* config options here */
  // This app serves live pipeline/model state (fetch({cache: "no-store"})) on
  // every request -- disabled so those routes render dynamically by default,
  // instead of fighting the opt-in "use cache"/Suspense model each route needs.
  cacheComponents: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
