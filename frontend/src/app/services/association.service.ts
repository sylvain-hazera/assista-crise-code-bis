import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  CandidatureAssociation, GrilleDisponibilites, InvitationAssociation, Qualification,
  QualificationMembre,
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
  private disponibilites = `${environment.apiUrl}/disponibilites-operationnelles`;

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

  enregistrerQualification(data: Partial<QualificationMembre>)
      : Observable<QualificationMembre> {
    return this.http.post<QualificationMembre>(`${this.qualificationsMembres}/`, data);
  }

  supprimerQualification(id: string): Observable<void> {
    return this.http.delete<void>(`${this.qualificationsMembres}/${id}/`);
  }

  // ── Disponibilités ──────────────────────────────────────────────────────────────────────

  /** La grille de mobilisation. `jours` est borné à 31 par le serveur : une grille de six mois
   * n'est pas une grille, c'est un export. */
  getGrille(institutionId: string, jours = 15): Observable<GrilleDisponibilites> {
    return this.http.get<GrilleDisponibilites>(`${this.disponibilites}/grille/`, {
      params: { institution: institutionId, jours: String(jours) },
    });
  }
}
