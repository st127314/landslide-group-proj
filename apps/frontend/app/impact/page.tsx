import ImpactMapLoader from "@/components/ImpactMapLoader";

export const metadata = { title: "Live Impact — Landslide Impact" };

// Full-bleed map: everything below the 3.5 rem header.
export default function ImpactPage() {
  return (
    <div className="relative h-[calc(100dvh-3.5rem)] w-full">
      <h1 className="sr-only">Live impact map</h1>
      <ImpactMapLoader />
    </div>
  );
}
