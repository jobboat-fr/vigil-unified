/**
 * Une date civile, écrite comme l'utilisateur la lit.
 *
 * `new Date().toISOString().slice(0, 10)` a l'air d'être le raccourci évident et ne l'est
 * pas : il convertit d'abord en UTC. À Paris (UTC+2 en été), minuit local du lundi
 * 31 août est 22 h 00 UTC le dimanche 30 — la chaîne obtenue est donc « 2026-08-30 »,
 * soit la veille.
 *
 * Le calendrier demandait par conséquent la semaine décalée d'un jour, ne recevait aucun
 * créneau et affichait « 0 créneau » sur une semaine qui en comptait deux ; la comparaison
 * `slot.on_date === iso(jour)` de la grille était décalée du même jour, si bien que rien
 * n'aurait été placé même avec les bonnes données. L'émargement, lui, ouvrait sur les
 * demi-journées de la veille entre minuit et 2 h du matin.
 *
 * Les dates de LEARN sont des dates civiles — `on_date`, `starts_on`, `ends_on` sont des
 * colonnes `date`, sans heure ni fuseau. Les formater dans le fuseau du navigateur est la
 * seule lecture correcte, et c'est ce que fait cette fonction.
 */
export function isoDay(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
