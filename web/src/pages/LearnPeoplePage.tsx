import { useCallback, useEffect, useState } from "react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@nous-research/ui/ui/components/card";
import {
  getProfiles,
  getAssignableRoles,
  LearnError,
  type Person,
  type Can,
} from "@/lib/learn";

const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super administrateur",
  admin: "Administration",
  formateur: "Formateur",
  entreprise: "Entreprise cliente",
  auditeur: "Auditeur",
  apprenant: "Apprenant",
  prospect: "Visiteur",
};

/**
 * Les comptes de l'organisme.
 *
 * La liste n'est pas la même pour deux appelants : une direction voit l'organisme, un
 * formateur voit les apprenants de ses sessions, un apprenant se voit lui-même. Ce fichier
 * ne le sait pas et n'a pas à le savoir — c'est la politique sur `learn_profiles` qui
 * restreint les lignes.
 *
 * Les rôles proposés à la création viennent de `/roles`, c'est-à-dire de
 * `learn_roles.creatable_roles`. Coder la liste en dur ici la ferait diverger le jour où la
 * hiérarchie change, et une hiérarchie d'autorisation qui existe en deux exemplaires est
 * une faille en attente.
 */
export default function LearnPeoplePage() {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [can, setCan] = useState<Can | null>(null);
  const [assignable, setAssignable] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const r = await getProfiles();
      setPeople(r.items);
      setCan(r._can ?? null);
    } catch (e) {
      setPeople([]);
      setError(e instanceof LearnError ? e.message : "Chargement impossible.");
    }
    try {
      const r = await getAssignableRoles();
      setAssignable(r.items.map((x) => x.role));
    } catch {
      setAssignable([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (people === null) return <p className="p-6 text-sm opacity-60">Chargement…</p>;

  const byRole = new Map<string, Person[]>();
  for (const p of people) {
    if (!byRole.has(p.role)) byRole.set(p.role, []);
    byRole.get(p.role)!.push(p);
  }

  return (
    <div className="space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Comptes et accès</h1>
        <p className="mt-1 text-sm opacity-70">
          {people.length} compte{people.length > 1 ? "s" : ""}
          {assignable.length > 0
            ? ` · vous pouvez créer : ${assignable.map((r) => ROLE_LABEL[r] ?? r).join(", ")}`
            : " · vous ne pouvez créer aucun compte"}
        </p>
      </header>

      {error ? (
        <Card>
          <CardContent className="p-4 text-sm">
            {error}{" "}
            <button className="underline" onClick={() => void load()}>
              Réessayer
            </button>
          </CardContent>
        </Card>
      ) : null}

      {people.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-sm opacity-70">
            Aucun compte visible depuis votre profil.
          </CardContent>
        </Card>
      ) : null}

      {[...byRole.entries()].map(([role, list]) => (
        <Card key={role}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {ROLE_LABEL[role] ?? role}{" "}
              <span className="text-sm font-normal opacity-60">({list.length})</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-current/10 text-sm">
              {list.map((p) => (
                <li key={p.id} className="flex flex-wrap items-baseline gap-x-4 px-4 py-2.5">
                  <span className="font-medium">{p.full_name || "—"}</span>
                  <span className="opacity-70">{p.email}</span>
                  {p.username ? (
                    <span className="opacity-60">identifiant : {p.username}</span>
                  ) : (
                    <span className="opacity-40">pas d&apos;identifiant court</span>
                  )}
                  {p.phone ? <span className="opacity-60">{p.phone}</span> : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ))}

      {can && !can.create ? (
        <p className="text-xs opacity-60">
          Votre profil ne permet pas de créer de compte. La règle vient de la hiérarchie des
          rôles en base, pas de cet écran.
        </p>
      ) : null}
    </div>
  );
}
