// Construit `web/public/vendor/three.global.js` à partir du paquet npm `three`.
// Le résultat est versionné : `public/` n'est pas traité par Vite, et le document Noyau
// le charge par une balise <script> classique.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const ici = dirname(fileURLToPath(import.meta.url));
await build({
  entryPoints: [resolve(ici, "three-global.js")],
  outfile: resolve(ici, "../public/vendor/three.global.js"),
  bundle: true,
  minify: true,
  format: "iife",
  target: "es2020",
  legalComments: "inline",
});
console.log("web/public/vendor/three.global.js écrit");
