import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AnnuaireAssociation,
  CandidatureAssociation, GrilleDisponibilites, InvitationAssociation, Qualification,
  QualificationMembre,
  QualificationsAVerifier,
} from '../shared/models/association.model';

/** Gestion des membres d'une association agréée de sécurité civile : candidatures, liens
 * d'invitation, qualifications et disponibilités.
 *
 * Un seul service pour les quatre : ce sont quatre facettes du même métier, et les séparer
 * obligerait la page à injecter quatre dépendances pour un seul écran. */
@Injectable({ providedIn: 'root' })
export class AssociationService {
  private candidatures = `${environment.apiUrl}/candidatures-association`;
  private invitations = `${environment.apiUrl}/invitations-association`;
  private qualifications = `${environment.apiUrl}/qualifications`;
  private qualificationsMembres = `${environment.apiUrl}/qualifications-membres`;
  // Le routeur DRF enregistre ce viewset sous `disponibilites` et non sous le nom du
  // modele : viser `disponibilites-operationnelles` renvoyait un 404 sur toute la grille,
  // y compris apres deploiement (constate le 28/10/2026 dans les journaux du proxy).
  private disponibilites = `${environment.apiUrl}/disponibilites`;
  private contacts = `${environment.apiUrl}/contacts-institutions`;

  constructor(private http: HttpClient) {}

  // ── Candidatures ────────────────────────────────────────────────────────────────────────

  getCandidatures(institutionId?: string): Observable<CandidatureAssociation[]> {
    // Typé explicitement : un objet vide littéral fait dériver l'inférence des surcharges de
    // HttpClient.get vers Observable<ArrayBuffer>, et l'erreur qui en sort ne parle pas du
    // vrai problème.
    const params: Record<string, string> = {};
    if (institutionId) { params['institution'] = institutionId; }
    return this.http.get<CandidatureAssociation[]>(`${this.candidatures}/`, { params });
  }

  /** Les quatre gestes du circuit. Jamais un PATCH sur `etape` : ce sont ces actions qui
   * portent les règles — qui a le droit, dans quel sens le circuit avance, et ce qu'une
   * acceptation déclenche (compte activé, rattachement posé, équipe rejointe). */
  prendreEnCharge(id: string): Observable<CandidatureAssociation> {
    return this.http.post<CandidatureAssociation>(
      `${this.candidatures}/${id}/prendre-en-charge/`, {});
  }

  marquerVerifiee(id: string): Observable<CandidatureAssociation> {
    return this.http.post<CandidatureAssociation>(`${this.candidatures}/${id}/verifier/`, {});
  }

  accepter(id: string): Observable<CandidatureAssociation> {
    return this.http.post<CandidatureAssociation>(`${this.candidatures}/${id}/accepter/`, {});
  }

  /** Le motif est exigé par le serveur : un refus sans raison se represente à l'identique six
   * mois plus tard, et personne ne sait pourquoi la personne avait été écartée. */
  refuser(id: string, motif: string): Observable<CandidatureAssociation> {
    return this.http.post<CandidatureAssociation>(
      `${this.candidatures}/${id}/refuser/`, { motif });
  }

  // ── Liens d'invitation ──────────────────────────────────────────────────────────────────

  getInvitations(): Observable<InvitationAssociation[]> {
    return this.http.get<InvitationAssociation[]>(`${this.invitations}/`);
  }

  creerInvitation(institutionId: string, libelle: string, dateExpiration: string | null)
      : Observable<InvitationAssociation> {
    const corps: Record<string, unknown> = { institution: institutionId };
    if (libelle) { corps['libelle'] = libelle; }
    // Date vide omise : l'API attend une date ou rien, jamais une chaîne vide.
    if (dateExpiration) { corps['date_expiration'] = dateExpiration; }
    return this.http.post<InvitationAssociation>(`${this.invitations}/`, corps);
  }

  desactiverInvitation(id: string): Observable<InvitationAssociation> {
    return this.http.patch<InvitationAssociation>(`${this.invitations}/${id}/`,
                                                  { actif: false });
  }

  // ── Qualifications ──────────────────────────────────────────────────────────────────────

  getCatalogueQualifications(): Observable<Qualification[]> {
    return this.http.get<Qualification[]>(`${this.qualifications}/`);
  }

  getQualificationsMembres(utilisateurId?: string): Observable<QualificationMembre[]> {
    const params: Record<string, string> = {};
    if (utilisateurId) { params['utilisateur'] = utilisateurId; }
    return this.http.get<QualificationMembre[]>(`${this.qualificationsMembres}/`, { params });
  }

  /** GET /api/qualifications-membres/a-verifier/ — ce qui attend une vérification.
   *
   * Sert la pastille de notification : sans un compteur, l'encadrement devrait déplier
   * l'arborescence entière pour découvrir qu'une pièce attend. */
  qualificationsAVerifier(): Observable<QualificationsAVerifier> {
    return this.http.get<QualificationsAVerifier>(`${this.qualificationsMembres}/a-verifier/`);
  }

  /** POST /api/qualifications-membres/ avec le fichier — `FormData` obligatoire.
   *
   * Le titulaire n'est pas envoyé : le serveur retombe sur l'appelant (CurrentUserDefault).
   * L'envoyer permettrait de déposer pour quelqu'un d'autre, ce que le serveur refuse de
   * toute façon sans droit sur la personne. */
  deposerJustificatif(qualificationId: string, fichier: File, champs: Record<string, string> = {})
      : Observable<QualificationMembre> {
    const corps = new FormData();
    corps.append('qualification', qualificationId);
    corps.append('justificatif', fichier);
    Object.entries(champs).forEach(([cle, valeur]) => {
      if (valeur) corps.append(cle, valeur);
    });
    return this.http.post<QualificationMembre>(`${this.qualificationsMembres}/`, corps);
  }

  /** PATCH avec un nouveau fichier : remet le titre à instruire côté serveur. */
  remplacerJustificatif(id: string, fichier: File): Observable<QualificationMembre> {
    const corps = new FormData();
    corps.append('justificatif', fichier);
    return this.http.patch<QualificationMembre>(`${this.qualificationsMembres}/${id}/`, corps);
  }

  /** Le fichier, en blob. **Jamais un `href` direct** : la route exige l'en-tête
   * d'authentification que pose l'intercepteur, qu'un `<a href>` n'enverrait pas — le
   * navigateur afficherait une page de refus. Et jamais une URL /media/ : cette route
   * contrôle les droits et journalise la consultation, savoir qui a regardé le diplôme de
   * quelqu'un fait partie de la protection. */
  telechargerJustificatif(id: string): Observable<Blob> {
    return this.http.get(`${this.qualificationsMembres}/${id}/justificatif/`,
                         { responseType: 'blob' });
  }

  /** Corrige le titre sous lequel une pièce a été déposée.
   *
   * Pas un détail d'affichage : c'est ce qui décide du sort du fichier. Un permis rangé sous
   * « Diplôme » serait conservé cinq ans au lieu d'être détruit à la validation. */
  requalifierPiece(id: string, qualificationId: string): Observable<QualificationMembre> {
    return this.http.post<QualificationMembre>(
      `${this.qualificationsMembres}/${id}/requalifier/`, { qualification: qualificationId });
  }

  /** Règle la catégorie de conservation d'une entrée du CATALOGUE — donc de toutes les
   * pièces déposées sous ce titre. Réservé aux comptes institutionnels côté serveur. */
  definirCategoriePiece(id: string, categorie: string): Observable<Qualification> {
    return this.http.patch<Qualification>(`${this.qualifications}/${id}/`,
                                          { categorie_piece: categorie });
  }

  verifierQualification(id: string): Observable<QualificationMembre> {
    return this.http.post<QualificationMembre>(`${this.qualificationsMembres}/${id}/verifier/`, {});
  }

  /** Le motif est obligatoire : sans lui le membre voit « refusé » sans savoir quoi corriger,
   * et redéposera la même pièce. */
  refuserQualification(id: string, motif: string): Observable<QualificationMembre> {
    return this.http.post<QualificationMembre>(
      `${this.qualificationsMembres}/${id}/refuser/`, { motif });
  }

  enregistrerQualification(data: Partial<QualificationMembre>)
      : Observable<QualificationMembre> {
    return this.http.post<QualificationMembre>(`${this.qualificationsMembres}/`, data);
  }

  supprimerQualification(id: string): Observable<void> {
    return this.http.delete<void>(`${this.qualificationsMembres}/${id}/`);
  }

  // ── Disponibilités ──────────────────────────────────────────────────────────────────────

  /** La grille de mobilisation, sur l'une des deux fenêtres.
   *
   * Sans `campagneId` : les `jours` qui viennent, bornés à 31 par le serveur — une grille de
   * six mois n'est pas une grille, c'est un export.
   *
   * Avec : la période de CETTE campagne, qui est souvent bien plus loin devant. C'est la seule
   * façon de voir des disponibilités à long terme : elles n'existent que parce qu'une campagne
   * les a demandées, et elles étaient jusqu'ici invisibles de l'écran qui sert à mobiliser. */
  getGrille(institutionId: string, jours = 15, campagneId?: string | null)
      : Observable<GrilleDisponibilites> {
    const params: Record<string, string> = { institution: institutionId };
    if (campagneId) { params['campagne'] = campagneId; }
    else { params['jours'] = String(jours); }
    return this.http.get<GrilleDisponibilites>(`${this.disponibilites}/grille/`, { params });
  }

  // ── Annuaire enrichi ────────────────────────────────────────────────────────────────────

  /** L'effectif, avec pour chacun fonction, compétences, coordonnées et état de ses titres.
   *
   * Un seul appel plutôt que quatre listes recoupées dans le navigateur : les informations
   * vivent dans quatre tables, et les assembler ici donnait quatre occasions de les voir
   * diverger. Les coordonnées sont servies au seul bureau — `coordonnees_visibles` dit
   * laquelle des deux réponses on vient de recevoir. */
  getAnnuaire(institutionId: string): Observable<AnnuaireAssociation> {
    return this.http.get<AnnuaireAssociation>(`${this.contacts}/annuaire-association/`, {
      params: { institution: institutionId },
    });
  }
}
