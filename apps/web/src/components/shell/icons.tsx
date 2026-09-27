// Minimal stroke icons (24px grid, 1.5px stroke) drawn for ORCA.
import type { SVGProps } from "react";

const I = (d: React.ReactNode) => function Icon(p: SVGProps<SVGSVGElement>) {
  return <svg viewBox="0 0 24 24" width={18} height={18} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" {...p}>{d}</svg>;
};

export const IcCommand = I(<><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="4" rx="1" /><rect x="14" y="10" width="7" height="11" rx="1" /><rect x="3" y="13" width="7" height="8" rx="1" /></>);
export const IcOcean = I(<><path d="M2 8c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" /><path d="M2 13c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" /><path d="M2 18c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2" /></>);
export const IcAsk = I(<><path d="M4 5h16v11H9l-5 4z" /><path d="M9 9.5h6M9 12.5h4" /></>);
export const IcFish = I(<><path d="M3 12c3-4 8-5 12-3l4-3v12l-4-3c-4 2-9 1-12-3z" /><circle cx="8" cy="11" r="0.8" fill="currentColor" /></>);
export const IcAlert = I(<><path d="M12 3l9.5 17h-19z" /><path d="M12 10v4.5M12 17.5v.01" /></>);
export const IcRoute = I(<><circle cx="5" cy="18" r="2" /><circle cx="19" cy="6" r="2" /><path d="M7 18h6a3 3 0 000-6H11a3 3 0 010-6h6" /></>);
export const IcResearch = I(<><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></>);
export const IcSources = I(<><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>);
export const IcAgents = I(<><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><circle cx="12" cy="13" r="2" /><path d="M12 7v4M10.5 14.5l-4 3M13.5 14.5l4 3" /></>);
export const IcEvidence = I(<><path d="M6 3h9l4 4v14H6z" /><path d="M15 3v4h4M9 12h7M9 16h5" /></>);
export const IcHealth = I(<><path d="M3 12h4l2-5 4 10 2-5h6" /></>);
export const IcEval = I(<><path d="M9 11l2 2 4-4" /><rect x="4" y="4" width="16" height="16" rx="2" /></>);
export const IcJudge = I(<><polygon points="8,5 19,12 8,19" /></>);
export const IcLayers = I(<><path d="M12 3l9 5-9 5-9-5z" /><path d="M3 13l9 5 9-5" /></>);

export function OrcaMark({ size = 22 }: { size?: number }) {
  // dorsal fin over three bathymetric contours
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
      <path d="M9 18C12 17 15 9 21 4c-1 6-1 10 2 14" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M3 21c4-2 9-2 13 0s9 2 13 0" stroke="var(--accent)" strokeWidth="1.6" opacity="0.9" />
      <path d="M3 25.5c4-2 9-2 13 0s9 2 13 0" stroke="var(--accent-2)" strokeWidth="1.4" opacity="0.7" />
      <path d="M3 30c4-2 9-2 13 0s9 2 13 0" stroke="var(--accent-2)" strokeWidth="1.2" opacity="0.4" />
    </svg>
  );
}
