import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Garde du 29/09 : dans un bloc `@theme inline`, Tailwind recopie la valeur dans la classe.
 * Une couleur littérale y devient donc indépendante du thème — c'est ce qui figeait
 * `text-success` en vert pâle (1,5:1) sur la charte claire. Dans ces blocs, une couleur doit
 * renvoyer à une variable (`var(...)`, `color-mix(... var(...))`), jamais être un littéral.
 */
describe("@theme inline ne fige aucune couleur", () => {
  it("aucun --color-* littéral dans un bloc inline", () => {
    const css = readFileSync(join(__dirname, "..", "index.css"), "utf-8");
    const blocs = [...css.matchAll(/@theme\s+inline\s*\{([\s\S]*?)\n\}/g)].map((m) => m[1]);
    expect(blocs.length).toBeGreaterThan(0);
    const figees = blocs.flatMap((b) =>
      [...b.matchAll(/(--color-[\w-]+)\s*:\s*(#[0-9a-f]{3,8}|rgb\(|hsl\()/gi)].map((m) => m[1]));
    expect(figees).toEqual([]);
  });
});
