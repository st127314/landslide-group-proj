"use client";

import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

type Theme = "light" | "dark" | "system";
const ORDER: Theme[] = ["light", "dark", "system"];
const LABEL: Record<Theme, string> = { light: "Light theme", dark: "Dark theme", system: "System theme" };

function apply(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function readStored(): Theme {
  try {
    const t = localStorage.getItem("theme");
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("system");

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setTheme(readStored());
  }, []);

  useEffect(() => {
    if (theme !== "system") return;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  const next = () => {
    const t = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    setTheme(t);
    apply(t);
    try {
      if (t === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", t);
    } catch {
      // Private mode: the choice just lasts for this page.
    }
  };

  return (
    <button
      type="button"
      onClick={next}
      title={`${LABEL[theme]} (click to change)`}
      aria-label={`${LABEL[theme]}, click to change`}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line text-muted transition-colors hover:bg-surface-2 hover:text-fg"
    >
      {theme === "light" && <Sun className="h-4 w-4" aria-hidden />}
      {theme === "dark" && <Moon className="h-4 w-4" aria-hidden />}
      {theme === "system" && <Monitor className="h-4 w-4" aria-hidden />}
    </button>
  );
}
