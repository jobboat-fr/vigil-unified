/**
 * Estampille le service worker avec l'empreinte du build.
 *
 * Sans cela `sw.js` est identique d'un déploiement à l'autre. Le navigateur compare les
 * octets : identiques, il ne réinstalle pas le worker, `activate` ne se rejoue pas, et le
 * cache des fichiers `/assets/` — servis « cache d'abord » — n'est jamais purgé. Le
 * navigateur reste alors sur un bundle périmé aussi longtemps qu'il garde le worker.
 *
 * L'empreinte est celle du fichier JS principal, qui change dès que le code change.
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const dist = new URL("../../hermes_cli/web_dist/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const entry = readdirSync(join(dist, "assets")).find((f) => /^index-.*\.js$/.test(f));
if (!entry) throw new Error("bundle principal introuvable dans web_dist/assets");

const stamp = entry.replace(/^index-/, "").replace(/\.js$/, "");
const swPath = join(dist, "sw.js");
const sw = readFileSync(swPath, "utf8");
if (!sw.includes("__BUILD__")) throw new Error("sw.js ne contient pas le marqueur __BUILD__");
writeFileSync(swPath, sw.replace("__BUILD__", stamp), "utf8");
console.log(`sw.js estampillé : vtlvs-${stamp}`);
