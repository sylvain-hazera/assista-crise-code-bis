/**
 * Le message que le SERVEUR a écrit, extrait d'une erreur HTTP d'Angular.
 *
 * Raison d'être : `HttpErrorResponse.message` est une phrase fabriquée par Angular — « Http
 * failure response for https://…/api/register/: 400 OK » — qui ne dit rien de ce qui s'est
 * passé et affiche une URL interne à quelqu'un qui essaie de créer son compte. Le vrai message
 * est dans `error.error`, et c'est lui qu'il faut montrer. Constaté en production le
 * 28/10/2026 : quatre tentatives d'inscription refusées de suite, la personne ne pouvant pas
 * savoir ce qu'on lui reprochait.
 *
 * Les quatre formes que renvoie ce backend, dans l'ordre où on les cherche :
 *
 * - une chaîne brute ;
 * - `{detail: "…"}` — les refus de permission de DRF ;
 * - `{error: "…"}` — les vues écrites à la main de ce projet ;
 * - `{champ: ["…"]}` — les erreurs de validation d'un sérialiseur.
 *
 * `repli` est rendu quand rien n'est exploitable : une erreur réseau, une passerelle qui
 * répond du HTML, ou un corps vide. Mieux vaut une phrase générique en français que la phrase
 * d'Angular, qui a l'air d'une fuite technique.
 */
export function messageErreurServeur(err: unknown, repli: string): string {
  const corps = (err as { error?: unknown })?.error;

  if (typeof corps === 'string' && corps.trim()) {
    // Une passerelle en panne renvoie une page HTML sous un content-type qui la fait passer
    // pour du texte : l'afficher telle quelle remplirait l'écran de balises.
    return corps.trim().startsWith('<') ? repli : corps.trim();
  }

  if (corps && typeof corps === 'object') {
    const objet = corps as Record<string, unknown>;
    for (const cle of ['detail', 'error', 'message']) {
      const valeur = objet[cle];
      if (typeof valeur === 'string' && valeur.trim()) return valeur.trim();
    }
    // Erreurs de validation : on rend le premier message lisible. Les nommer toutes
    // produirait un pavé ; le formulaire souligne par ailleurs les champs fautifs.
    for (const valeur of Object.values(objet)) {
      if (Array.isArray(valeur) && typeof valeur[0] === 'string' && valeur[0].trim()) {
        return valeur[0].trim();
      }
      if (typeof valeur === 'string' && valeur.trim()) return valeur.trim();
    }
  }

  return repli;
}
