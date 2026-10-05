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
