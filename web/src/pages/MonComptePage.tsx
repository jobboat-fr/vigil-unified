import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@nous-research/ui/ui/components/card";
import { Button } from "@nous-research/ui/ui/components/button";
import { useAuth } from "@/context/AuthContext";
import { useLearnRole } from "@/lib/supabase";
import { compte, LIENS_LEGAUX } from "@/lib/compte";

const ROLES: Record<string, string> = {
  super_admin: "Éditeur de la plateforme", admin: "Direction de l'organisme", formateur: "Formateur",
  entreprise: "Entreprise cliente", auditeur: "Auditeur", apprenant: "Apprenant",
};

/**
 * Mon compte : ce que la plateforme sait de moi, et le droit de partir.
 * Export (RGPD art. 15 et 20) et suppression (art. 17), expliqués sans jargon, avant le bouton.
 */
export default function MonComptePage() {
  const { user, signOut } = useAuth();
  const { role } = useLearnRole();
  const [exportEtat, setExportEtat] = useState<"repos" | "cours" | "pret" | "erreur">("repos");
  const [exportMsg, setExportMsg] = useState("");
  const [etape, setEtape] = useState<"repos" | "confirmer" | "cours" | "fait">("repos");
  const [saisie, setSaisie] = useState("");
  const [motif, setMotif] = useState("");
  const [erreur, setErreur] = useState("");

  const exporter = async () => {
    setExportEtat("cours");
    try {
      const data = await compte.exporter();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `mes-donnees-vtlvs-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setExportEtat("pret");
    } catch (e) {
      setExportEtat("erreur");
      setExportMsg((e as Error).message);
    }
  };

  const supprimer = async () => {
    setEtape("cours");
    setErreur("");
    try {
      await compte.supprimer(saisie, motif || undefined);
      setEtape("fait");
      setTimeout(() => void signOut(), 4000);
    } catch (e) {
      setEtape("confirmer");
      setErreur((e as Error).message);
    }
  };

  if (etape === "fait") {
    return (
      <div className="mx-auto flex max-w-lg flex-col gap-3 py-16 text-center">
        <h1 className="text-xl font-semibold">Votre compte est supprimé</h1>
        <p className="text-sm text-text-secondary">
          Merci d'avoir fait partie de la plateforme. Les preuves de formation que la loi oblige à garder restent conservées, sans votre nom.
          Vous allez être déconnecté.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 pb-8">
      <Card>
        <CardHeader><CardTitle>Mon identité</CardTitle></CardHeader>
        <CardContent className="grid gap-3 text-sm sm:grid-cols-2">
          <div><p className="text-xs text-text-secondary">Adresse e-mail</p><p className="break-all">{user?.email}</p></div>
          <div><p className="text-xs text-text-secondary">Rôle</p><p>{ROLES[role ?? ""] ?? "—"}</p></div>
          <p className="text-xs text-text-secondary sm:col-span-2">
            Votre rôle est attribué par votre organisme de formation ; pour le changer, adressez-vous à sa direction.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Mes données</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <p>
            Téléchargez tout ce que la plateforme conserve à votre sujet : profil, inscriptions, émargements, documents signés,
            évaluations, actions, notifications, documents du studio, demandes d'aide. Un fichier lisible, tout de suite.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => void exporter()} disabled={exportEtat === "cours"}>
              {exportEtat === "cours" ? "Préparation…" : "Télécharger mes données"}
            </Button>
            {exportEtat === "pret" && <span className="text-xs" style={{ color: "#059669" }}>Fichier téléchargé.</span>}
            {exportEtat === "erreur" && <span className="text-xs" style={{ color: "#e11d48" }}>{exportMsg}</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Supprimer mon compte</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-current/10 p-3">
              <p className="font-medium">Ce qui disparaît</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-text-secondary">
                <li>Votre nom, votre e-mail, votre téléphone</li>
                <li>Vos documents et tableaux du studio, vos partages</li>
                <li>Vos actions en attente, vos jetons de calendrier</li>
                <li>L'accès à votre compte, définitivement</li>
              </ul>
            </div>
            <div className="rounded-lg border border-current/10 p-3">
              <p className="font-medium">Ce qui reste, sans votre nom</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-text-secondary">
                <li>Émargements et documents signés</li>
                <li>Résultats d'évaluation</li>
                <li>Pièces du coffre, jusqu'à leur échéance légale</li>
              </ul>
              <p className="mt-2 text-xs text-text-secondary">L'organisme doit pouvoir prouver qu'une formation a eu lieu (Code du travail, Qualiopi).</p>
            </div>
          </div>

          {role === "super_admin" ? (
            <p className="text-xs text-text-secondary">Le compte éditeur ne se supprime pas depuis cet écran : la plateforme doit toujours avoir un éditeur.</p>
          ) : etape === "repos" ? (
            <div><Button ghost onClick={() => setEtape("confirmer")}>Je veux supprimer mon compte</Button></div>
          ) : (
            <div className="flex flex-col gap-2 rounded-lg border p-3" style={{ borderColor: "#e11d4855" }}>
              <label className="text-xs" htmlFor="motif">Un mot sur la raison (facultatif, nous aide à nous améliorer)</label>
              <textarea id="motif" rows={2} value={motif} onChange={(e) => setMotif(e.target.value)}
                className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-sm outline-none" />
              <label className="text-xs" htmlFor="conf">Pour confirmer, écrivez <strong>SUPPRIMER</strong></label>
              <input id="conf" value={saisie} onChange={(e) => setSaisie(e.target.value)} autoComplete="off"
                className="rounded-md border border-current/20 bg-transparent px-3 py-2 text-base outline-none" />
              {erreur && <p className="text-xs" style={{ color: "#e11d48" }}>{erreur}</p>}
              <div className="flex flex-wrap gap-2">
                <button type="button" disabled={saisie.trim().toUpperCase() !== "SUPPRIMER" || etape === "cours"}
                  onClick={() => void supprimer()}
                  className="rounded-md px-4 py-2 text-sm font-medium text-white disabled:opacity-40" style={{ background: "#be123c" }}>
                  {etape === "cours" ? "Suppression…" : "Supprimer définitivement"}
                </button>
                <Button ghost onClick={() => { setEtape("repos"); setSaisie(""); setErreur(""); }}>Garder mon compte</Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <nav className="flex flex-wrap gap-x-4 gap-y-1 px-1 text-xs text-text-secondary" aria-label="Documents légaux">
        {LIENS_LEGAUX.map((l) => <a key={l.href} href={l.href} target="_blank" rel="noreferrer" className="underline-offset-2 hover:underline">{l.label}</a>)}
      </nav>
    </div>
  );
}
