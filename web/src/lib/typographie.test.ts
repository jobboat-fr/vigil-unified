/**
 * Garde permanente (29/09) : la typographie Hermes ne revient pas.
 * Hauteur de ligne nulle = libellés superposés sur téléphone ; espacement ≥ 0,1 em = boutons
 * et menus illisibles ; le bouton et la carte du kit portaient les deux.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function fichiers(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? fichiers(p) : /\.(tsx|ts)$/.test(n) ? [p] : [];
  });
}

const SRC = join(__dirname, "..");
const sansCommentaires = (p: string) =>
  readFileSync(p, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
const code = fichiers(SRC).filter((p) => !p.endsWith("typographie.test.ts"));

describe("typographie VTLVS", () => {
  it("aucune hauteur de ligne nulle", () => {
    const fautifs = code.filter((p) => /\bleading-0\b|leading-\[0\]/.test(readFileSync(p, "utf8").replace(/\/\*[\s\S]*?\*\//g, "")));
    expect(fautifs).toEqual([]);
  });
  it("aucun espacement de lettres ≥ 0,1 em", () => {
    const fautifs = code.filter((p) => /tracking-\[0\.[1-9]\d*em\]/.test(sansCommentaires(p)));
    expect(fautifs).toEqual([]);
  });
  it("le bouton et la carte viennent de VTLVS, plus du kit Hermes", () => {
    const fautifs = code.filter((p) => /@nous-research\/ui\/ui\/components\/(button|card)"/.test(readFileSync(p, "utf8")));
    expect(fautifs).toEqual([]);
  });
});
