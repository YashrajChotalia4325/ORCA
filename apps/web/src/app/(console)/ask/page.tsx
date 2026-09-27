"use client";
import AskPanel from "@/components/ask/AskPanel";
import { IntelPanel, PanelHeader } from "@/components/shell/ConsoleShell";
import { useOrca } from "@/lib/store";

export default function AskPage() {
  const mode = useOrca((s) => s.mode);
  return (
    <IntelPanel width={500}>
      <PanelHeader kicker="Ask ORCA · multi-agent reasoning" title="Ask the ocean" right={<span className="lbl" style={{ color: mode === "LIVE" ? "var(--live)" : mode === "DEMO" ? "var(--demo)" : "var(--replay)" }}>{mode}</span>} />
      <AskPanel />
    </IntelPanel>
  );
}
