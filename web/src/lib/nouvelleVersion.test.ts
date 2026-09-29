import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { estEchecDeModule, rechargerPourNouvelleVersion } from "./nouvelleVersion";

describe("onglet plus vieux que le déploiement", () => {
  let stockage: Map<string, string>;
  const reload = vi.fn();

  beforeEach(() => {
    stockage = new Map();
    reload.mockReset();
    vi.stubGlobal("sessionStorage", {
      getItem: (k: string) => stockage.get(k) ?? null,
      setItem: (k: string, v: string) => void stockage.set(k, v),
    });
    vi.stubGlobal("window", { location: { reload } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it("reconnaît l'échec d'import de chaque navigateur, et rien d'autre", () => {
    for (const m of [
      "Importing a module script failed.",
      "Failed to fetch dynamically imported module: https://app.vtlvs.com/assets/X-abc.js",
      "error loading dynamically imported module",
      "Unable to preload CSS for /assets/x.css",
    ]) expect(estEchecDeModule(new Error(m)), m).toBe(true);
    expect(estEchecDeModule(new Error("Cannot read properties of undefined"))).toBe(false);
    expect(estEchecDeModule(null)).toBe(false);
  });

  it("recharge une fois, puis laisse l'écran d'incident parler plutôt que de boucler", () => {
    expect(rechargerPourNouvelleVersion()).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
    expect(rechargerPourNouvelleVersion()).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("stockage bloqué : ne recharge pas (sinon rien n'empêcherait une boucle)", () => {
    vi.stubGlobal("sessionStorage", {
      getItem: () => { throw new Error("SecurityError"); },
      setItem: () => { throw new Error("SecurityError"); },
    });
    expect(rechargerPourNouvelleVersion()).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});
