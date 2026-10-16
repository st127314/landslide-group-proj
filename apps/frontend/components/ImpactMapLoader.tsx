"use client";

import dynamic from "next/dynamic";

// maplibre-gl touches `window`/WebGL at module scope, so this must never run
// during server-side rendering. `ssr: false` is only allowed inside a Client
// Component, hence this thin wrapper around the actual ImpactMap.
const ImpactMap = dynamic(() => import("@/components/ImpactMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center text-sm text-zinc-500">
      Loading map…
    </div>
  ),
});

export default function ImpactMapLoader() {
  return <ImpactMap />;
}
