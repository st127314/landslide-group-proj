// Shared frame for the content pages: title block, evenly spaced sections and a footer with the project credits.
export default function Page({
  title,
  description,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <div className="mb-6 max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description && <p className="mt-2 text-[15px] leading-relaxed text-muted">{description}</p>}
        </div>
        <div className="space-y-6">{children}</div>
      </div>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-5 text-xs text-muted sm:flex-row sm:justify-between sm:px-6">
          <span>AT82.03 Machine Learning · Asian Institute of Technology</span>
          <span>Data: OpenStreetMap, WorldPop 2020, NOAA GFS, CHIRPS, Google Earth Engine</span>
        </div>
      </footer>
    </div>
  );
}

/** Shown when the data service cannot be reached: a plain message, with the technical cause behind an expander. */
export function LoadError({ what, error, hint }: { what: string; error: string; hint?: React.ReactNode }) {
  return (
    <div role="alert" className="note-danger">
      <p className="font-medium">{what} could not be loaded.</p>
      <p className="mt-1">The data service did not answer. Reload the page in a few minutes.</p>
      <details className="mt-2 text-xs">
        <summary className="cursor-pointer">Technical detail</summary>
        <p className="mt-1">
          <code>{error}</code>
        </p>
        {hint && <p className="mt-1">{hint}</p>}
      </details>
    </div>
  );
}
