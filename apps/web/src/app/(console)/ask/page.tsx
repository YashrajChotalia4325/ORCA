"use client";
import AskPanel from "@/components/ask/AskPanel";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { useQueryParam } from "@/lib/hooks";
import { useOrca } from "@/lib/store";

export default function AskPage() {
  const mode = useOrca((s) => s.mode);
  const q = useQueryParam("q");   // prefilled question from the home page (?q=…)
  return (
    <IntelPanel width={500}>
      <PanelHeader kicker="Ask ORCA · multi-agent reasoning" title="Ask the ocean" right={<span className="lbl" style={{ color: mode === "LIVE" ? "var(--live)" : mode === "DEMO" ? "var(--demo)" : "var(--replay)" }}>{mode}</span>} />
      <AskPanel key={q ?? ""} presetQuery={q} />
    </IntelPanel>
  );
}
