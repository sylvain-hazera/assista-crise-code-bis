import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';

import { BrouillonsEnvoiService } from './brouillons-envoi.service';

/** En-tête par lequel le serveur annonce les messages retenus pour relecture.
 * Doit figurer dans `CORS_EXPOSE_HEADERS` côté Django, sinon il arrive bien mais reste
 * invisible au JavaScript — la requête réussit et la fonctionnalité ne marche pas, sans
 * qu'aucune erreur n'apparaisse. */
const EN_TETE = 'X-Brouillons-Envoi';

/**
 * Repère les messages retenus pour relecture et les signale au service, qui ouvre la fenêtre.
 *
 * **Pourquoi un intercepteur** : un message est retenu en conséquence d'une action — valider un
 * compte, clôturer un dossier, inviter un membre — et il y a 25 endpoints concernés. Les faire
 * tous répondre « voici le brouillon que j'ai créé » demanderait de changer 25 contrats d'API
 * et leurs appelants, et le vingt-sixième écrit demain l'oublierait. Le serveur pose un en-tête,
 * cet intercepteur le lit : aucun endpoint ne change, et tout envoi futur est couvert
 * automatiquement.
 *
 * Même raisonnement que `collectiviteInterceptor` : un contexte transversal se traite une fois,
 * pas à 25 endroits.
 */
export const brouillonsEnvoiInterceptor: HttpInterceptorFn = (req, next) => {
  const service = inject(BrouillonsEnvoiService);
  return next(req).pipe(
    tap(evenement => {
      if (!(evenement instanceof HttpResponse)) return;
      const annonce = evenement.headers.get(EN_TETE);
      if (!annonce) return;
      service.signaler(annonce.split(',').map(i => i.trim()).filter(Boolean));
    }),
  );
};
