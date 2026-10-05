const base = { fill: "none", stroke: "currentColor", strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const Check = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" strokeWidth="3" {...base}><polyline points="20 6 9 17 4 12" /></svg>
);

export const Cross = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" strokeWidth="3" {...base}><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
);

export const ChevronLeft = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth="2" {...base}><polyline points="15 18 9 12 15 6" /></svg>
);

export const ChevronRight = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" strokeWidth="2" {...base}><polyline points="9 18 15 12 9 6" /></svg>
);

export const ChevronDown = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth="2" {...base}><polyline points="6 9 12 15 18 9" /></svg>
);

export const Code = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth="2" {...base}><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg>
);

export const Download = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth="2" {...base}><path d="M12 3v12" /><polyline points="7 10 12 15 17 10" /><path d="M5 21h14" /></svg>
);

export const Plus = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" strokeWidth="2" {...base}><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
);
