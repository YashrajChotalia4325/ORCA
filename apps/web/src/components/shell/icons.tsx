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

// home-page / stakeholder icons (same grid and stroke)
export const IcLanguage = I(<><path d="M4 5h9M8.5 3v2M6 5c0 4 2.5 7 6 8.5M11 5c-.5 4-3 7-7 8.5" /><path d="M13 21l4-9 4 9M14.5 18h5" /></>);
export const IcAnchor = I(<><circle cx="12" cy="5" r="2" /><path d="M12 7v14M8 10h8M4 13c0 4.5 3.6 8 8 8s8-3.5 8-8" /></>);
export const IcClock = I(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>);
export const IcBoatSmall = I(<><path d="M3 14h18l-3 5H6z" /><path d="M12 14V6M12 6l5 6h-5" /></>);
export const IcTrawler = I(<><path d="M2 15h20l-3 5H5z" /><path d="M6 15v-4h7v4M9 11V7h2v4M16 15V5l4 9" /></>);
export const IcShip = I(<><path d="M2 16h20l-3 5H5z" /><path d="M5 16v-5h14v5M9 11V7h6v4M11 7V4h2v3" /></>);
export const IcSun = I(<><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>);
export const IcSunrise = I(<><path d="M5 18a7 7 0 0114 0M2 18h20M12 3v5M9 6l3-3 3 3M4.2 11.2l1.4 1.4M19.8 11.2l-1.4 1.4" /><path d="M5 22h14" /></>);
export const IcSunset = I(<><path d="M5 18a7 7 0 0114 0M2 18h20M12 3v5M9 5l3 3 3-3M4.2 11.2l1.4 1.4M19.8 11.2l-1.4 1.4" /><path d="M5 22h14" /></>);
export const IcShield = I(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" /><path d="M9 12l2 2 4-4" /></>);
export const IcPeople = I(<><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2.5" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M15 14.5c3 0 6 2 6 5.5" /></>);
export const IcCap = I(<><path d="M2 9l10-5 10 5-10 5z" /><path d="M6 11v5c3 2 9 2 12 0v-5M22 9v6" /></>);
export const IcScope = I(<><path d="M9 3h4l1 5-3 1-2-6zM11 9l3 8" /><path d="M6 21h12M9 21a5 5 0 017-7" /></>);
export const IcShare = I(<><circle cx="18" cy="5" r="2.5" /><circle cx="6" cy="12" r="2.5" /><circle cx="18" cy="19" r="2.5" /><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4" /></>);
export const IcCopy = I(<><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3" /></>);
export const IcMap = I(<><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z" /><path d="M9 4v14M15 6v14" /></>);
export const IcBook = I(<><path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2z" /><path d="M4 19V5M8 7h7" /></>);
export const IcCyclone = I(<><path d="M12 12m-3 0a3 3 0 106 0 3 3 0 10-6 0" /><path d="M21 7c-2-3-6-4-9-4-5 0-9 4-9 9M3 17c2 3 6 4 9 4 5 0 9-4 9-9" /></>);
export const IcScale = I(<><path d="M12 4v16M7 20h10M5 7h14" /><path d="M5 7l-3 6a3 3 0 006 0zM19 7l-3 6a3 3 0 006 0z" /></>);
export const IcSignal = I(<><path d="M12 20v-6M8.5 10.5a5 5 0 017 0M5.5 7.5a9 9 0 0113 0" /><path d="M3 3l18 18" /></>);
export const IcLeaf = I(<><path d="M5 19C5 10 11 4 20 4c0 9-6 15-15 15z" /><path d="M5 19l8-8" /></>);
export const IcArrowUp = I(<><path d="M12 20V5M6 11l6-6 6 6" /></>);

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
