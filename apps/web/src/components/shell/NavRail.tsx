"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as I from "./icons";

const NAV = [
  { href: "/command", label: "Command", icon: I.IcCommand },
  { href: "/ocean", label: "Live Ocean", icon: I.IcOcean },
  { href: "/ask", label: "Ask ORCA", icon: I.IcAsk },
  { href: "/fishing", label: "Fishing", icon: I.IcFish },
  { href: "/safety", label: "Safety", icon: I.IcAlert },
  { href: "/route", label: "Route", icon: I.IcRoute },
  { href: "/research", label: "Research", icon: I.IcResearch },
  { sep: true },
  { href: "/sources", label: "Sources", icon: I.IcSources },
  { href: "/agents", label: "Agents", icon: I.IcAgents },
  { href: "/evidence", label: "Evidence", icon: I.IcEvidence },
  { href: "/health", label: "Health", icon: I.IcHealth },
  { href: "/eval", label: "Eval", icon: I.IcEval },
  { sep: true },
  { href: "/judge", label: "Judge", icon: I.IcJudge },
] as const;

export default function NavRail() {
  const path = usePathname();
  return (
    <nav className="z-20 flex w-[68px] shrink-0 flex-col items-stretch gap-0.5 border-r border-line bg-panel py-2" aria-label="ORCA sections">
      {NAV.map((n, i) => {
        if ("sep" in n) return <div key={i} className="mx-3 my-1.5 border-t border-line" />;
        const active = path?.startsWith(n.href);
        const Icon = n.icon;
        return (
          <Link key={n.href} href={n.href} aria-current={active ? "page" : undefined}
            className={`group relative mx-1.5 flex flex-col items-center gap-1 rounded-md py-2 transition-colors ${active ? "bg-panel-3 text-accent" : "text-ink-3 hover:bg-panel-2 hover:text-ink-2"}`}>
            {active && <span className="absolute left-[-6px] top-2 bottom-2 w-[2px] rounded bg-accent" />}
            <Icon />
            <span className="font-cond text-[9.5px] tracking-[0.06em]">{n.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
