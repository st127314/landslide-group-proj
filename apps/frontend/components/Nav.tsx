"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChartColumn, CloudRain, LayoutDashboard, Map, Mountain } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/impact", label: "Live Impact", icon: Map },
  { href: "/warning", label: "Early Warning", icon: CloudRain },
  { href: "/model", label: "Model", icon: ChartColumn },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 h-14 border-b border-line bg-surface/90 backdrop-blur">
      <div className="mx-auto flex h-full max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent text-accent-fg">
            <Mountain className="h-5 w-5" aria-hidden />
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
                className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-3 text-sm font-medium transition-colors ${
                  active ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"
                }`}
              >
                <link.icon className="hidden h-4 w-4 md:block" aria-hidden />
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
