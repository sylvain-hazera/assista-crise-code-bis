import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  Creneau, FicheBenevole, MesDisponibilites,
} from '../shared/models/fiche-benevole.model';

/** Fiche du compte connecté, et son mot de passe.
 *
 * Les URL ne portent AUCUN identifiant : c'est toujours la fiche de l'appelant. C'est ce qui
 * rend impossible, par construction, de lire celle de quelqu'un d'autre par cette route. */
@Injectable({ providedIn: 'root' })
export class FicheBenevoleService {

  private url = `${environment.apiUrl}/ma-fiche-benevole/`;
  private urlMotDePasse = `${environment.apiUrl}/definir-mon-mot-de-passe/`;
  private urlDisponibilites = `${environment.apiUrl}/mes-disponibilites/`;

  constructor(private http: HttpClient) {}

  /** La fiche est créée au premier appel : l'écran doit s'ouvrir sur un formulaire vide, pas
   * sur une erreur. */
  maFiche(): Observable<FicheBenevole> {
    return this.http.get<FicheBenevole>(this.url);
  }

  /** Le secteur n'est pas envoyé : il est en lecture seule côté serveur, posé par le
   * géocodage de l'adresse. Un changement d'adresse peut donc changer d'équipe
   * départementale — et retirer de l'ancienne. */
  enregistrer(champs: Partial<FicheBenevole>): Observable<FicheBenevole> {
    return this.http.patch<FicheBenevole>(this.url, champs);
  }

  /** Mes créneaux, quatre par jour sur quinze jours.
   *
   * Écrit dans `DisponibiliteOffre` — **le seul moteur de disponibilité du projet**, celui
   * que lit `/admin/teams` pour constituer une équipe et que remplit déjà le formulaire
   * public « proposer mon aide ». Ce guichet n'est pas une seconde source : il évite au membre
   * de devoir connaître l'identifiant de sa ressource pour cocher une case. */
  mesDisponibilites(jours = 15, campagne?: string | null): Observable<MesDisponibilites> {
    const params: Record<string, string> = { jours: String(jours) };
    // Une campagne impose SA période : sans ce paramètre, on répondrait sur ses quinze
    // prochains jours — à une autre question que celle posée.
    if (campagne) { params['campagne'] = campagne; }
    return this.http.get<MesDisponibilites>(this.urlDisponibilites, { params });
  }

  /** « Je ne suis pas disponible sur cette période » : une réponse, dite en un geste. Sans
   * elle, répondre non voulait dire ne rien cocher — donc être relancé. */
  repondreIndisponible(campagne: string): Observable<{ etat: string }> {
    return this.http.post<{ etat: string }>(`${this.urlDisponibilites}indisponible/`,
                                            { campagne });
  }

  /** Coche ou décoche un créneau. `creneau` omis = **toute la journée**, soit quatre lignes.
   *
   * Décocher SUPPRIME la ligne : « pas de ligne = indisponible » est la règle de ce moteur
   * depuis l'origine, il n'y a pas de ligne « indisponible » à écrire. */
  declarerCreneau(date: string, disponible: boolean, creneau?: Creneau,
                  campagne?: string | null)
      : Observable<{ date: string; creneaux: Creneau[]; disponible: boolean }> {
    const corps: Record<string, unknown> = { date, disponible };
    if (creneau) { corps['creneau'] = creneau; }
    // C'est ce rattachement qui fait d'un créneau coché une RÉPONSE à la campagne.
    if (campagne) { corps['campagne'] = campagne; }
    return this.http.post<{ date: string; creneaux: Creneau[]; disponible: boolean }>(
      this.urlDisponibilites, corps);
  }

  /** Aucun ancien mot de passe demandé : un compte créé par import n'en a pas, et en exiger
   * un l'empêcherait d'en choisir un. L'appelant est déjà authentifié par son lien magique,
   * dont la possession prouve l'accès à la boîte mail. */
  definirMotDePasse(nouveau: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(this.urlMotDePasse,
                                               { nouveau_mot_de_passe: nouveau });
  }
}
