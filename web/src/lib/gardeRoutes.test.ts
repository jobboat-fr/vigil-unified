import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { cheminsRefuses, navAllowed, type EntreeGardee } from "./gardeRoutes";

const ROLES = ["super_admin", "admin", "formateur", "entreprise", "apprenant", "auditeur"];

const MENU: EntreeGardee[] = [
  { path: "/aide", label: "Aide" },
  { path: "/profiles", label: "Profils agent", roles: ["super_admin"] },
  { path: "/ops-team", label: "Équipe agentique", roles: ["super_admin", "admin"], capability: ["ops", "read"] },
  { path: "/studio", label: "Studio", roles: ["admin", "formateur"] },
  { path: "/studio/projets", label: "Projets", roles: ["admin", "formateur", "apprenant"] },
];
const CHEMINS = ["/aide", "/profiles", "/profiles/new", "/ops-team", "/studio", "/studio/projets", "/studio/projets/x"];

describe("garde des routes", () => {
  it("chaque route, pour chaque rôle : la page, ou l'écran de refus — jamais autre chose", () => {
    for (const role of ROLES) {
      const refus = cheminsRefuses(MENU, CHEMINS, role, null);
      for (const n of MENU) expect(refus.has(n.path), `${role} ${n.path}`).toBe(!navAllowed(n, role, null));
    }
  });

  it("une sous-adresse hérite du garde de sa page parente la plus proche", () => {
    const admin = cheminsRefuses(MENU, CHEMINS, "admin", null);
    expect(admin.get("/profiles/new")).toBe("Profils agent");
    const apprenant = cheminsRefuses(MENU, CHEMINS, "apprenant", null);
    expect(apprenant.has("/studio")).toBe(true);
    // /studio/projets est ouvert à l'apprenant : sa sous-adresse aussi, malgré le /studio fermé.
    expect(apprenant.has("/studio/projets/x")).toBe(false);
  });

  it("une fois connus, les droits de la passerelle priment sur la liste de rôles", () => {
    const perms = { role: "admin", grants: { ops: [] as string[] } };
    expect(cheminsRefuses(MENU, CHEMINS, "admin", perms).has("/ops-team")).toBe(true);
    expect(cheminsRefuses(MENU, CHEMINS, "formateur", { role: "formateur", grants: { ops: ["read"] } }).has("/ops-team")).toBe(false);
  });

  it("sans rôle résolu, une page réservée reste fermée", () => {
    expect(cheminsRefuses(MENU, CHEMINS, null, null).has("/profiles")).toBe(true);
  });
});

/**
 * La garde ne vaut que si chaque route y passe. Une route ajoutée sans entrée de menu, sans page
 * parente, et hors de la liste ci-dessous serait ouverte à tous sans que personne l'ait décidé.
 */
const OUVERTES_A_TOUS: Record<string, string> = {
  "/": "redirige vers l'accueil du rôle",
  "/accueil/documents/:id": "le document à signer de la personne elle-même",
  "/offres": "« Voir tout ce que nous proposons », ouverte à tous les rôles (29/09)",
};

describe("chaque route d'App.tsx passe par la garde", () => {
  it("entrée de menu, page parente, ou ouverture décidée", () => {
    const src = readFileSync(join(__dirname, "..", "App.tsx"), "utf-8");
    const bloc = src.slice(src.indexOf("const BUILTIN_ROUTES_CORE"));
    const routes = [...bloc.slice(0, bloc.indexOf("\n};")).matchAll(/^\s*"(\/[^"]*)":/gm)].map((m) => m[1]);
    const menu = new Set([...src.matchAll(/\{\s*path:\s*"(\/[^"]*)"/g)].map((m) => m[1]));
    expect(routes.length).toBeGreaterThan(40);
    const orphelines = routes.filter(
      (r) => !menu.has(r) && ![...menu].some((p) => r.startsWith(`${p}/`)) && !(r in OUVERTES_A_TOUS));
    expect(orphelines).toEqual([]);
  });
});
