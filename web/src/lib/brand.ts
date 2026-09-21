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

// Les surfaces sombres — la salle de réunion, l'écran d'invitation — ne peuvent pas porter
// le bleu de marque tel quel : `#1d3fae` sur `#07080d` ne se distingue pas du fond. Elles
// avaient donc hérité d'un dégradé violet → cyan qui n'appartient à aucune marque et qu'on
// trouve sur la moitié des produits d'IA. C'est précisément le signal inverse de celui
// qu'on cherche.
//
// Deux jetons remplacent ce dégradé.
//
// `plaque` est une chute de lumière verticale, pas une rampe de teintes : une arête claire
// en haut, le corps au milieu, une arête sombre en bas. C'est ce qui fait lire une surface
// comme du métal — trois valeurs d'une même couleur, et non deux couleurs différentes. Le
// texte dessus est l'encre de marque, jamais du blanc.
//
// `accentSombre` est le bleu de marque éclairci jusqu'à être lisible sur du quasi-noir.
// Même famille, donc même marque ; assez clair pour un liseré ou un mot d'alerte.
export const METAL = {
  plaque: "linear-gradient(180deg,#f3f6fb 0%,#dde3ec 52%,#c4ccd9 100%)",
  areteHaute: "rgba(255,255,255,0.80)",
  areteBasse: "rgba(6,10,18,0.45)",
  encre: "#0b2239",
  accentSombre: "#7aa2ff",
} as const;
