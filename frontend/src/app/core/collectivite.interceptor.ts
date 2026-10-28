import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { CollectiviteConsulteeService } from './collectivite-consultee.service';

/** Les endpoints territoriaux, c'est-à-dire ceux qui répondent « pour quelle collectivité ? ».
 * Liste explicite plutôt qu'un préfixe large : un intercepteur qui ajoute un paramètre à des
 * appels qui ne l'attendent pas est une source de bugs impossibles à relier à leur cause. */
const CHEMINS_TERRITORIAUX = ['/vue_mairie/', '/vue_secteur/'];

/**
 * Ajoute `?commune=` aux appels territoriaux quand l'utilisateur consulte une collectivité qui
 * n'est pas la sienne.
 *
 * Pourquoi un intercepteur plutôt que huit signatures de service : « quelle collectivité je
 * regarde » est un contexte transversal, comme une langue ou un fuseau. Le passer en argument
 * obligerait chacun des huit appels de « Vue Ma Collectivité » à le transporter, et le
 * neuvième écrit demain l'oublierait — alors que c'est précisément l'oubli qui produit une
 * page qui affiche le territoire de quelqu'un d'autre.
 *
 * Le paramètre ne CRÉE aucun droit : le serveur vérifie à chaque appel que la commune est dans
 * le périmètre accordé et répond 403 sinon (voir `zone_scoping._institution_commune_or_400`).
 * Un paramètre déjà posé par l'appelant n'est jamais écrasé : un écran qui demande
 * explicitement une commune sait mieux que ce contexte global.
 */
export const collectiviteInterceptor: HttpInterceptorFn = (req, next) => {
  const commune = inject(CollectiviteConsulteeService).communeChoisie;
  if (!commune) return next(req);
  if (!CHEMINS_TERRITORIAUX.some(chemin => req.url.includes(chemin))) return next(req);
  if (req.params.has('commune')) return next(req);
  return next(req.clone({ params: req.params.set('commune', commune) }));
};
