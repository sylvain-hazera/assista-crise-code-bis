import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { FicheBenevole } from '../shared/models/fiche-benevole.model';

/** Fiche du compte connecté, et son mot de passe.
 *
 * Les URL ne portent AUCUN identifiant : c'est toujours la fiche de l'appelant. C'est ce qui
 * rend impossible, par construction, de lire celle de quelqu'un d'autre par cette route. */
@Injectable({ providedIn: 'root' })
export class FicheBenevoleService {

  private url = `${environment.apiUrl}/ma-fiche-benevole/`;
  private urlMotDePasse = `${environment.apiUrl}/definir-mon-mot-de-passe/`;

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

  /** Aucun ancien mot de passe demandé : un compte créé par import n'en a pas, et en exiger
   * un l'empêcherait d'en choisir un. L'appelant est déjà authentifié par son lien magique,
   * dont la possession prouve l'accès à la boîte mail. */
  definirMotDePasse(nouveau: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(this.urlMotDePasse,
                                               { nouveau_mot_de_passe: nouveau });
  }
}
