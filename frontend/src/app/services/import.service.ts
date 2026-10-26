import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface ImportApercu {
  colonnes: string[];
  apercu: Record<string, string>[];
  total_lignes: number;
}

export interface ImportResultat {
  crees: number;
  rattaches?: number;   // absent pour l'import d'institutions (pas de notion de rattachement)
  erreurs: { ligne: number; message: string }[];
}

export interface SaisiePersonne {
  prenom: string;
  nom: string;
  email: string;
  telephone: string;
  fonction: string;
  inviter: boolean;
}

@Injectable({ providedIn: 'root' })
export class ImportService {
  private readonly url = `${environment.apiUrl}/imports`;

  constructor(private http: HttpClient) {}

  /** POST /api/imports/apercu/ — en-têtes détectées + 10 premières lignes, pour l'étape de
   * correspondance des colonnes avant l'import réel. */
  apercu(fichier: File): Observable<ImportApercu> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    return this.http.post<ImportApercu>(`${this.url}/apercu/`, fd);
  }

  /** POST /api/imports/personnel-communal/ — importe le personnel communal/élus en comptes
   * complets pour l'institution de l'utilisateur connecté. `mapping` associe chaque champ cible
   * (prenom/nom/email/telephone/fonction) au nom de la colonne détectée dans le fichier. */
  importerPersonnelCommunal(fichier: File, mapping: Record<string, string>): Observable<ImportResultat> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    Object.entries(mapping).forEach(([champ, colonne]) => {
      if (colonne) fd.append(`mapping_${champ}`, colonne);
    });
    return this.http.post<ImportResultat>(`${this.url}/personnel-communal/`, fd);
  }

  /** POST /api/imports/personnel-communal/saisie/ — mêmes comptes créés que l'import de
   * fichier, mais pour quelques personnes tapées à la main. `inviter` (vrai par défaut) ne
   * décide que de l'envoi du mail d'invitation ; le rattachement à la collectivité a lieu
   * dans tous les cas. */
  saisirPersonnelCommunal(personnes: SaisiePersonne[]): Observable<ImportResultat> {
    return this.http.post<ImportResultat>(`${this.url}/personnel-communal/saisie/`, { personnes });
  }

  /** GET /api/imports/personnel-communal/exemple/ — fichier CSV d'exemple à télécharger avant
   * de préparer son propre fichier. */
  telechargerExemplePersonnelCommunal(): Observable<Blob> {
    return this.http.get(`${this.url}/personnel-communal/exemple/`, { responseType: 'blob' });
  }

  /** POST /api/imports/institutions/ — crée des institutions en masse. `mapping` associe
   * chaque champ cible (nom/type/description/telephone/email/adresse) à la colonne détectée.
   * `type` doit correspondre au libellé exact d'un InstitutionType déjà existant. */
  importerInstitutions(fichier: File, mapping: Record<string, string>): Observable<ImportResultat> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    Object.entries(mapping).forEach(([champ, colonne]) => {
      if (colonne) fd.append(`mapping_${champ}`, colonne);
    });
    return this.http.post<ImportResultat>(`${this.url}/institutions/`, fd);
  }

  telechargerExempleInstitutions(): Observable<Blob> {
    return this.http.get(`${this.url}/institutions/exemple/`, { responseType: 'blob' });
  }

  /** POST /api/imports/correspondants-pcs/ — importe les correspondants PCS (rôles DOS/RAC/
   * Correspondants...) en comptes complets + affectations de rôle pour l'institution de
   * l'utilisateur connecté. `role` doit correspondre au libellé exact d'un RoleOperationnel
   * déjà existant (voir l'onglet « Rôles opérationnels »). */
  importerCorrespondantsPCS(fichier: File, mapping: Record<string, string>): Observable<ImportResultat> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    Object.entries(mapping).forEach(([champ, colonne]) => { if (colonne) fd.append(`mapping_${champ}`, colonne); });
    return this.http.post<ImportResultat>(`${this.url}/correspondants-pcs/`, fd);
  }

  telechargerExempleCorrespondantsPCS(): Observable<Blob> {
    return this.http.get(`${this.url}/correspondants-pcs/exemple/`, { responseType: 'blob' });
  }

  /** POST /api/imports/interlocuteurs-pcs/ — importe l'annuaire d'alerte PCS/PICS (catalogue
   * partagé, voir InterlocuteurAlertePCS) pour l'institution de l'utilisateur connecté. */
  importerInterlocuteursPCS(fichier: File, mapping: Record<string, string>): Observable<ImportResultat> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    Object.entries(mapping).forEach(([champ, colonne]) => { if (colonne) fd.append(`mapping_${champ}`, colonne); });
    return this.http.post<ImportResultat>(`${this.url}/interlocuteurs-pcs/`, fd);
  }

  telechargerExempleInterlocuteursPCS(): Observable<Blob> {
    return this.http.get(`${this.url}/interlocuteurs-pcs/exemple/`, { responseType: 'blob' });
  }

  /** POST /api/imports/materiel-point/ — importe le matériel d'UN point opérationnel précis
   * (`pointId`, jamais une colonne du fichier) -- voir imports.importer_materiel_point. */
  importerMaterielPoint(fichier: File, pointId: string, mapping: Record<string, string>): Observable<ImportResultat> {
    const fd = new FormData();
    fd.append('fichier', fichier);
    fd.append('point_id', pointId);
    Object.entries(mapping).forEach(([champ, colonne]) => { if (colonne) fd.append(`mapping_${champ}`, colonne); });
    return this.http.post<ImportResultat>(`${this.url}/materiel-point/`, fd);
  }

  telechargerExempleMaterielPoint(): Observable<Blob> {
    return this.http.get(`${this.url}/materiel-point/exemple/`, { responseType: 'blob' });
  }
}
