/**
 * Titre d'une demande, d'une offre ou d'un signalement déposé par le public (21/11/2026).
 *
 * « Offre d'aide - Crue du Gier — exercice - Inondation - Bénévolat » ne disait rien au
 * régulateur : la crise est déjà un champ à part, et c'est la nature et le lieu qui se lisent
 * dans une liste. Un signalement prenait, lui, le début de sa description. Désormais :
 * « Pompage — Rive-de-Gier », « Bénévolat — Saint-Chamond — Garage Martin »,
 * « Arbre sur la chaussée — Rive-de-Gier ». Jamais de nom de personne : le titre n'est pas
 * chiffré et s'affiche dans des listes.
 */
export function titreDepot(quoi: string | null | undefined, commune?: string | null, complement?: string | null): string {
  const morceaux = [quoi, commune, complement].map(m => (m ?? '').trim()).filter(m => !!m);
  return (morceaux.join(' — ') || 'Dépôt').slice(0, 255);
}
