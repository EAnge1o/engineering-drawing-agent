import { html } from "./html.js";

const PATHS = {
  cube: "M12 2 3 7v10l9 5 9-5V7l-9-5Zm0 2.3 6.5 3.6L12 11.5 5.5 7.9 12 4.3ZM5 9.7l6 3.3v6.4l-6-3.3V9.7Zm8 9.7V13l6-3.3v6.4l-6 3.3Z",
  upload: "M12 3v10m0-10 4 4m-4-4-4 4M4 15v3a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3v-3",
  shield: "M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3Z",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z",
  download: "M12 4v10m0 0 4-4m-4 4-4-4M5 19h14",
  rotate: "M20 12a8 8 0 1 1-2.3-5.6M20 4v5h-5",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  check: "M4 12.5 9 17.5 20 6.5",
  alert: "M12 3 2 20h20L12 3Zm0 6v5m0 3v.5",
  doc: "M6 3h8l4 4v14H6zM14 3v4h4",
  bolt: "M13 2 4 14h7l-1 8 9-12h-7l1-8Z",
  target: "M12 3v3m0 12v3M3 12h3m12 0h3M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6 6 18",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0",
  play: "M8 5v14l11-7L8 5Z",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 5v.5m0 3v5",
  filter: "M4 5h16l-6 7v6l-4 2v-8L4 5Z",
  chevron: "M9 5l7 7-7 7",
};

export function Ico({ name, size = 16, cls = "" }) {
  return html`<svg class=${cls} viewBox="0 0 24 24" width=${size} height=${size} fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${PATHS[name] || PATHS.cube} /></svg>`;
}

export function BrandMark() {
  return html`<svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 2 3 7v10l9 5 9-5V7l-9-5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round" />
    <path d="M12 6.5 7 9.2v5.6l5 2.7 5-2.7V9.2l-5-2.7Z" stroke="currentColor" stroke-width="1.2" opacity=".65" />
    <circle cx="12" cy="12" r="1.7" fill="currentColor" />
  </svg>`;
}