"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import ThemeToggle from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/impact", label: "Live Impact" },
  { href: "/warning", label: "Early Warning" },
  { href: "/model", label: "Model" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 h-14 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-full max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-fg">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden>
              <path d="M2 20 9 8l4 6 3-4 6 10z" />
            </svg>
          </span>
          <span className="leading-tight">
            <span className="block text-sm font-semibold tracking-tight">Landslide Impact</span>
            <span className="hidden text-[11px] text-muted sm:block">Southern Thailand</span>
          </span>
        </Link>
        <nav className="-mb-px flex h-full flex-1 items-stretch gap-1 overflow-x-auto">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center whitespace-nowrap border-b-2 px-3 text-sm font-medium transition-colors ${
                  active ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
        <ThemeToggle />
      </div>
    </header>
  );
}
