import { ChevronRight } from "lucide-react";

// Building blocks shared by the content pages, so every page has the same card, heading and spacing rules:
// one h1 (in Page), an h2 per Section, h3 inside a section. Sections are spaced by the page, not by themselves.

/** Small upper-case label above a value. Uses the muted colour, which meets contrast in both themes. */
export const LABEL = "text-xs font-medium uppercase tracking-wider text-muted";

/** Text link style. */
export const LINK = "font-medium text-accent underline-offset-2 hover:underline";

export function Section({
  id,
  title,
  description,
  children,
}: {
  id: string;
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="card scroll-mt-20">
      <h2 id={`${id}-title`} className="card-title">
        {title}
      </h2>
      {description && <p className="card-desc max-w-3xl leading-relaxed">{description}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Detail that most readers do not need: closed by default, opened with a click or the keyboard. */
export function Details({ summary, children }: { summary: React.ReactNode; children: React.ReactNode }) {
  return (
    <details className="group rounded-lg border border-line bg-surface-2/60">
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight className="h-4 w-4 shrink-0 text-muted transition-transform group-open:rotate-90" aria-hidden />
        {summary}
      </summary>
      <div className="border-t border-line px-3 py-3 text-sm leading-relaxed text-muted">{children}</div>
    </details>
  );
}

/** A term and its plain-language meaning, used in "how to read this" lists. */
export function Definition({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-sm font-semibold">{term}</dt>
      <dd className="mt-1 space-y-2 text-sm leading-relaxed text-muted">{children}</dd>
    </div>
  );
}

/** A horizontally scrollable table frame that can be reached and scrolled with the keyboard. */
export function TableScroll({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div role="region" aria-label={label} tabIndex={0} className="overflow-x-auto rounded-lg border border-line">
      {children}
    </div>
  );
}

/** Classes for the first column of a wide table, so the row name stays visible while the rest scrolls. */
export const STICKY_COL = "sticky left-0 z-10 bg-surface [tr:hover_&]:bg-surface-2";
export const STICKY_HEAD = "sticky left-0 z-10";
