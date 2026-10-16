import ImpactMapLoader from "@/components/ImpactMapLoader";

export default function ImpactPage() {
  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto w-full max-w-6xl px-6 pt-6">
        <h1 className="text-2xl font-bold tracking-tight">Live Impact</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Susceptibility sample points, critical facilities and buildings over the study area.
          Buildings load for the current map viewport only (426k+ footprints total).
        </p>
      </div>
      <div className="mx-auto mt-4 h-[70vh] w-full max-w-6xl px-6 pb-10">
        <div className="h-full w-full overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-800">
          <ImpactMapLoader />
        </div>
      </div>
    </div>
  );
}
