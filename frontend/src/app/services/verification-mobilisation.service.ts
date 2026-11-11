import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';

/** Verdict rendu par la vérification d'une attestation.
 *
 * `connue` distingue « ce QR n'est pas des nôtres » de « cette attestation a été révoquée » :
 * les deux sont `valide: false`, et ce ne sont pas du tout les mêmes situations sur le
 * terrain. */
export interface VerdictMobilisation {
  valide: boolean;
  connue: boolean;
  motif: string;
  /** Faux quand l'appelant n'était pas authentifié : le serveur a alors retiré le nom du
   * destinataire et le lieu de rendez-vous. L'écran le DIT, plutôt que d'afficher des champs
   * vides — un champ vide se lit comme une donnée manquante, pas comme une donnée retenue. */
  complet?: boolean;
  statut?: string;
  statut_libelle?: string;
  reference?: string;
  institution_emettrice?: string;
  destinataire?: string;
  crise?: string;
  nature?: string;
  lieu?: string;
  date_creation?: string;
  date_revocation?: string | null;
}

/** Vérification d'une attestation de mobilisation à partir de son jeton.
 *
 * **Endpoint public** (`AllowAny` côté serveur) : le jeton EST l'autorisation, comme pour la
 * page que le QR ouvre dans le navigateur d'un gendarme sans compte. Le service n'ajoute donc
 * aucune authentification — et le serveur n'expose rien de plus que cette page publique. */
@Injectable({ providedIn: 'root' })
export class VerificationMobilisationService {

  constructor(private http: HttpClient) {}

  verifier(jeton: string): Observable<VerdictMobilisation> {
    return this.http.get<VerdictMobilisation>(
      `${environment.apiUrl}/verifier-mobilisation/${encodeURIComponent(jeton)}/donnees/`);
  }

  /** Extrait le jeton de ce qu'a lu la caméra.
   *
   * Le QR contient une URL complète (`https://…/api/verifier-mobilisation/<jeton>/`), mais on
   * accepte aussi un jeton nu : c'est ce qu'on saisit à la main quand la caméra n'est pas
   * disponible, et refuser cette forme priverait les iPhone de toute vérification intégrée.
   *
   * Renvoie null quand le texte scanné n'a rien à voir — un QR de carte de visite, par
   * exemple. L'écran le dit alors, plutôt que d'interroger le serveur avec n'importe quoi. */
  jetonDepuisTexte(texte: string): string | null {
    const brut = (texte || '').trim();
    if (!brut) { return null; }

    const motif = /verifier-mobilisation\/([^/?#\s]+)/.exec(brut);
    if (motif) { return decodeURIComponent(motif[1]); }

    // Jeton nu : `secrets.token_urlsafe(32)` donne 43 caractères de l'alphabet URL-safe.
    // Borné pour ne pas envoyer au serveur une phrase entière lue sur un autre QR.
    if (/^[A-Za-z0-9_-]{20,64}$/.test(brut)) { return brut; }

    return null;
  }
}
