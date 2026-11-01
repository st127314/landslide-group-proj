// Shared frame for the content pages: title block, body and a footer with the project credits.
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
        <div className="mb-8 max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          {description && <div className="mt-2 text-[15px] leading-relaxed text-muted">{description}</div>}
        </div>
        {children}
      </div>
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 px-4 py-5 text-xs text-subtle sm:flex-row sm:justify-between sm:px-6">
          <span>AT82.03 Machine Learning · Asian Institute of Technology</span>
          <span>Data: OpenStreetMap, WorldPop 2020, NOAA GFS, CHIRPS, Google Earth Engine</span>
        </div>
      </footer>
    </div>
  );
}
