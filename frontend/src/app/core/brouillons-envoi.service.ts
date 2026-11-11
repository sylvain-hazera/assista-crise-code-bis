import { HttpClient } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  BrouillonEnvoi, ModeleCatalogue, ModeleMessage,
} from '../shared/models/brouillon-envoi.model';

/** Messages retenus pour relecture, et textes réécrits par une institution.
 *
 * `aRelire` est un signal : l'intercepteur HTTP y dépose les identifiants annoncés par le
 * serveur en en-tête `X-Brouillons-Envoi`, et le composant de relecture, monté une fois dans
 * la coquille de l'application, ouvre la fenêtre. C'est ce qui permet à la fenêtre de s'ouvrir
 * après N'IMPORTE QUELLE action, sans qu'aucun des 25 endpoints concernés ne change de
 * contrat. */
@Injectable({ providedIn: 'root' })
export class BrouillonsEnvoiService {

  private url = `${environment.apiUrl}/brouillons-envoi`;
  private urlModeles = `${environment.apiUrl}/modeles-messages`;

  /** Identifiants annoncés par le serveur pendant la dernière action. */
  readonly aRelire = signal<string[]>([]);

  constructor(private http: HttpClient) {}

  /** Appelé par l'intercepteur. Empile plutôt que remplace : une action peut produire
   * plusieurs messages (inviter trois membres d'un coup), et n'en montrer qu'un ferait partir
   * les autres sans relecture au bout du délai. */
  signaler(identifiants: string[]): void {
    if (!identifiants.length) return;
    this.aRelire.update(actuels => [...actuels, ...identifiants.filter(i => !actuels.includes(i))]);
  }

  /** Retire un identifiant de la file, qu'il ait été envoyé ou abandonné. */
  retirer(id: string): void {
    this.aRelire.update(actuels => actuels.filter(i => i !== id));
  }

  get(id: string): Observable<BrouillonEnvoi> {
    return this.http.get<BrouillonEnvoi>(`${this.url}/${id}/`);
  }

  /** Les brouillons encore à relire, pour la liste : un message annoncé pendant une action
   * manquée (onglet fermé, rechargement) doit rester trouvable. */
  aRelireListe(): Observable<BrouillonEnvoi[]> {
    return this.http.get<BrouillonEnvoi[]>(`${this.url}/`, { params: { statut: 'A_RELIRE' } });
  }

  /** `sujet`/`corps` omis = le texte capturé part tel quel. Les `[LIEN_n]` conservés dans le
   * texte sont remplacés par les vraies URL côté serveur, au seul moment de l'envoi. */
  envoyer(id: string, sujet?: string, corps?: string): Observable<BrouillonEnvoi> {
    const corpsRequete: Record<string, string> = {};
    if (sujet !== undefined) corpsRequete['sujet'] = sujet;
    if (corps !== undefined) corpsRequete['corps'] = corps;
    return this.http.post<BrouillonEnvoi>(`${this.url}/${id}/envoyer/`, corpsRequete);
  }

  /** Le motif est obligatoire : l'action qui a produit le message a déjà eu lieu, et personne
   * ne sera prévenu. */
  abandonner(id: string, motif: string): Observable<BrouillonEnvoi> {
    return this.http.post<BrouillonEnvoi>(`${this.url}/${id}/abandonner/`, { motif });
  }

  catalogue(): Observable<ModeleCatalogue[]> {
    return this.http.get<ModeleCatalogue[]>(`${this.urlModeles}/catalogue/`);
  }

  modelesDe(institutionId: string): Observable<ModeleMessage[]> {
    return this.http.get<ModeleMessage[]>(`${this.urlModeles}/`,
                                          { params: { institution: institutionId } });
  }

  creerModele(data: Partial<ModeleMessage>): Observable<ModeleMessage> {
    return this.http.post<ModeleMessage>(`${this.urlModeles}/`, data);
  }

  majModele(id: string, data: Partial<ModeleMessage>): Observable<ModeleMessage> {
    return this.http.patch<ModeleMessage>(`${this.urlModeles}/${id}/`, data);
  }

  supprimerModele(id: string): Observable<void> {
    return this.http.delete<void>(`${this.urlModeles}/${id}/`);
  }
}
