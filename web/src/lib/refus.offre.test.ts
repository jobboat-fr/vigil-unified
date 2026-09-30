import { describe, expect, it, vi } from "vitest";
import { expliquer } from "./refus";

// Un refus d'offre (402) s'explique, puis porte de quoi montrer l'offre d'entrée (Azer, 29/09).
const refus402 = (detail: Record<string, unknown>) => ({ status: 402, code: String(detail.error), detail });

describe("refus d'offre → offre d'entrée", () => {
  it("agent refusé à l'administration : l'offre de CET agent, souscription possible", () => {
    const x = expliquer(refus402({ error: "abonnement_requis", agent: "azzco", role: "admin",
      message: "Cette fonction est réservée aux organismes abonnés à AZZCO." }), "le Studio");
    expect(x.registre).toBe("offre");
    expect(x.reessayable).toBe(false);
    expect(x.offre).toEqual({ agent: "azzco", peutSouscrire: true });
  });

  it("agent refusé à un apprenant : l'offre, mais pas de bouton qui mènerait à « accès réservé »", () => {
    const x = expliquer(refus402({ error: "abonnement_requis", agent: "azzmin", role: "apprenant" }));
    expect(x.offre).toEqual({ agent: "azzmin", peutSouscrire: false });
    expect(x.geste).toBeUndefined();
    expect(x.detail).toMatch(/administration de votre organisme/);
  });

  it("plafond de l'offre gratuite : titre clair, phrase du serveur, ressource transmise", () => {
    const x = expliquer(refus402({ error: "plafond_offre_gratuite", ressource: "projets", limite: 1, role: "admin",
      message: "L'offre gratuite comprend 1 projet. Une formule payante ouvre la plateforme sans plafond." }));
    expect(x.titre).toBe("L'offre gratuite s'arrête ici");
    expect(x.detail).toMatch(/1 projet/);
    expect(x.offre).toEqual({ ressource: "projets", peutSouscrire: true });
  });

  it("un agent inconnu dans la réponse n'est pas repris tel quel", () => {
    const x = expliquer(refus402({ error: "abonnement_requis", agent: "<script>", role: "admin" }));
    expect(x.offre?.agent).toBeNull();
  });

  it("le créneau de l'assistant reste un cas à part, sans offre", () => {
    const x = expliquer(refus402({ error: "assistant_hors_formation" }));
    expect(x.offre).toBeUndefined();
  });
});

describe("refus d'offre lu en une ligne → fenêtre d'offre", () => {
  it("annonce une fois, pas à chaque rendu ; rien pour une erreur ordinaire", async () => {
    const { expliquerCourt, EVENEMENT_OFFRE } = await import("./refus");
    const recus: unknown[] = [];
    const cible = new EventTarget();
    cible.addEventListener(EVENEMENT_OFFRE, (ev) => recus.push((ev as CustomEvent).detail));
    vi.stubGlobal("window", cible);
    try {
      const e = refus402({ error: "abonnement_requis", agent: "azzcom", role: "admin" });
      expliquerCourt(e, "la relance");
      expliquerCourt(e, "la relance"); // re-rendu : même refus
      expliquerCourt({ status: 500 }, "la liste");
      await Promise.resolve();
      expect(recus).toHaveLength(1);
      expect((recus[0] as { offre: unknown }).offre).toEqual({ agent: "azzcom", peutSouscrire: true });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("lien vers les journaux", () => {
  it("cherche la référence exacte dans Loki, tous services", async () => {
    const { lienJournaux } = await import("./reference");
    const u = new URL(lienJournaux("3c824844aa55bb66cc77dd88ee99ff00"));
    expect(u.origin).toBe("https://grafana.vtlvs.com");
    const panes = JSON.parse(u.searchParams.get("panes")!);
    expect(panes.a.queries[0].expr).toBe('{service=~".+"} |= "3c824844aa55bb66cc77dd88ee99ff00"');
    expect(panes.a.datasource).toBe("loki-vtlvs");
  });
});
