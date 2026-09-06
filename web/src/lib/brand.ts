// Shared VTLVS brand tokens, so the auth screen, the loading state and the onboarding
// wizard match the dashboard and the vitrine rather than each other.
//
// These are constants rather than CSS variables because the screens that use them render
// before ThemeProvider has applied a theme — a loader that reads `var(--background)` shows
// an unstyled flash on first paint. Keeping them in one file means the palette is changed
// once, not in four components.
//
// Values are copied from `hbs-formation/tailwind.config.ts`. A visitor meets the organisme
// on the vitrine and continues here; two palettes read as two companies.
export const BRAND = {
  bg: "#f4f7fb",      // cloud — the canvas
  ink: "#0b2239",     // navy — text
  gold: "#1d3fae",    // the brand accent. Named `gold` because four components import it
                      // under that name; renaming it is a separate change from recolouring
                      // it, and doing both at once makes neither reviewable.
  emer: "#1f7a4c",    // success
  rose: "#c0392b",    // error
  panel: "#ffffff",   // cards sit ABOVE the canvas on a light theme, not below it
  line: "rgba(11,34,57,0.10)",
  display: "'Poppins', 'Inter', system-ui, sans-serif",
  mono: "'JetBrains Mono', ui-monospace, 'Cascadia Mono', Menlo, monospace",
} as const;
