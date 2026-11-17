import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import {
  AppareilStock, ArticleStock, BilanImportStock, CommandeStock, DemandeTransfertStock, DisponibiliteStock, LotTypeStock, ReservationStock, VerificationLot, DepotStock, EtatStock, EtatStockPoint, FactureStock, GesteStockPoint, LigneCommandeStock, LigneInventaire,
  MouvementStock, PretMateriel, SaisieMouvement, TiersStock,
} from '../shared/models/stock.model';

/** Gestion des stocks de l'institution (voir core/stocks.py côté serveur). */
@Injectable({ providedIn: 'root' })
export class StockService {
  private readonly url = `${environment.apiUrl}/stocks`;

  constructor(private http: HttpClient) {}

  etat(depot?: string): Observable<EtatStock> {
    const params: Record<string, string> = depot ? { depot } : {};
    return this.http.get<EtatStock>(`${this.url}/etat/`, { params });
  }

  exporter(): Observable<Blob> {
    return this.http.get(`${this.url}/etat/`, { params: { format_fichier: 'csv' }, responseType: 'blob' });
  }

  creerArticle(article: Partial<ArticleStock>): Observable<ArticleStock> {
    return this.http.post<ArticleStock>(`${this.url}/articles/`, article);
  }

  modifierArticle(id: string, article: Partial<ArticleStock>): Observable<ArticleStock> {
    return this.http.patch<ArticleStock>(`${this.url}/articles/${id}/`, article);
  }

  creerDepot(depot: Partial<DepotStock>): Observable<DepotStock> {
    return this.http.post<DepotStock>(`${this.url}/depots/`, depot);
  }

  modifierDepot(id: string, depot: Partial<DepotStock>): Observable<DepotStock> {
    return this.http.patch<DepotStock>(`${this.url}/depots/${id}/`, depot);
  }

  mouvements(filtres: { article?: string; depot?: string } = {}): Observable<MouvementStock[]> {
    const params: Record<string, string> = {};
    if (filtres.article) params['article'] = filtres.article;
    if (filtres.depot) params['depot'] = filtres.depot;
    return this.http.get<MouvementStock[]>(`${this.url}/mouvements/`, { params });
  }

  /** `quantite` toujours positive : entrée, sortie, quantité déplacée ou quantité COMPTÉE. */
  enregistrer(saisie: SaisieMouvement): Observable<{ mouvements: MouvementStock[]; stock?: string; detail?: string; avertissement?: string }> {
    return this.http.post<{ mouvements: MouvementStock[]; stock?: string; detail?: string; avertissement?: string }>(`${this.url}/mouvements/`, saisie);
  }

  /** Le stock d'un point d'accueil, d'après le journal. */
  point(pointId: string): Observable<EtatStockPoint> {
    return this.http.get<EtatStockPoint>(`${this.url}/points/${pointId}/`);
  }

  /** Doter le point depuis un dépôt, y recevoir, distribuer, compter, ou rapatrier le reste. */
  gestePoint(pointId: string, geste: GesteStockPoint, corps: Record<string, unknown>): Observable<EtatStockPoint> {
    return this.http.post<EtatStockPoint>(`${this.url}/points/${pointId}/${geste}/`, corps);
  }

  /** Reprise d'un export Dolibarr ou d'un tableur. `simuler` : dit ce qui serait fait. */
  importer(fichier: File, depot: string, simuler: boolean): Observable<BilanImportStock> {
    const formulaire = new FormData();
    formulaire.append('fichier', fichier);
    if (depot) formulaire.append('depot', depot);
    if (simuler) formulaire.append('simuler', '1');
    return this.http.post<BilanImportStock>(`${this.url}/import/`, formulaire);
  }

  // ── Inventaire d'un dépôt ───────────────────────────────────────────────────────────────
  /** La feuille à imprimer ; `aveugle` : sans les quantités attendues. */
  feuilleInventaire(depot: string, aveugle: boolean): Observable<Blob> {
    return this.http.get(`${this.url}/etat/`, { params: { depot, format_fichier: 'pdf', ...(aveugle ? { aveugle: '1' } : {}) }, responseType: 'blob' });
  }

  lignesInventaire(depot: string): Observable<{ depot: string; depot_nom: string; lignes: LigneInventaire[] }> {
    return this.http.get<{ depot: string; depot_nom: string; lignes: LigneInventaire[] }>(`${this.url}/inventaire/`, { params: { depot } });
  }

  /** Ce qu'on a compté, saisi d'un bloc. */
  saisirInventaire(depot: string, comptes: { article: string; quantite: number; lot?: string; date_peremption?: string }[]):
      Observable<{ comptees: number; corrections: MouvementStock[] }> {
    return this.http.post<{ comptees: number; corrections: MouvementStock[] }>(`${this.url}/inventaire/`, { depot, comptes });
  }

  // ── Tiers ───────────────────────────────────────────────────────────────────────────────
  tiers(recherche = ''): Observable<TiersStock[]> {
    const params: Record<string, string> = recherche ? { recherche } : {};
    return this.http.get<TiersStock[]>(`${this.url}/tiers/`, { params });
  }

  enregistrerTiers(tiers: Partial<TiersStock>): Observable<TiersStock> {
    return tiers.id ? this.http.patch<TiersStock>(`${this.url}/tiers/${tiers.id}/`, tiers) : this.http.post<TiersStock>(`${this.url}/tiers/`, tiers);
  }

  // ── Commandes et factures ───────────────────────────────────────────────────────────────
  commandes(): Observable<CommandeStock[]> { return this.http.get<CommandeStock[]>(`${this.url}/commandes/`); }

  enregistrerCommande(commande: { id?: string; tiers: string; depot?: string | null; livraison_prevue?: string | null; commentaire?: string;
                                  lignes: LigneCommandeStock[] }): Observable<CommandeStock> {
    return commande.id ? this.http.patch<CommandeStock>(`${this.url}/commandes/${commande.id}/`, commande)
      : this.http.post<CommandeStock>(`${this.url}/commandes/`, commande);
  }

  /** `passer` (le brouillon part), `annuler`, ou `recevoir` avec les quantités reçues. */
  gesteCommande(id: string, geste: 'passer' | 'annuler' | 'recevoir', corps: Record<string, unknown> = {}): Observable<CommandeStock> {
    return this.http.post<CommandeStock>(`${this.url}/commandes/${id}/${geste}/`, corps);
  }

  factures(): Observable<FactureStock[]> { return this.http.get<FactureStock[]>(`${this.url}/factures/`); }

  creerFacture(facture: Record<string, string>, piece: File | null): Observable<FactureStock> {
    const formulaire = new FormData();
    Object.entries(facture).forEach(([cle, valeur]) => { if (valeur !== '' && valeur !== null && valeur !== undefined) formulaire.append(cle, valeur); });
    if (piece) formulaire.append('fichier', piece);
    return this.http.post<FactureStock>(`${this.url}/factures/`, formulaire);
  }

  payerFacture(id: string, payeeLe: string | null): Observable<FactureStock> {
    return this.http.patch<FactureStock>(`${this.url}/factures/${id}/`, { payee_le: payeeLe });
  }

  pieceFacture(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/factures/${id}/piece/`, { responseType: 'blob' });
  }

  // ── Prêts ───────────────────────────────────────────────────────────────────────────────
  prets(): Observable<PretMateriel[]> { return this.http.get<PretMateriel[]>(`${this.url}/prets/`); }

  ouvrirPret(pret: Record<string, unknown>): Observable<PretMateriel> {
    return this.http.post<PretMateriel>(`${this.url}/prets/`, pret);
  }

  /** La fiche de retour : état, constat, quantité rendue. */
  rendrePret(id: string, retour: { etat_retour: string; constat_retour?: string; quantite_rendue?: string | number }): Observable<PretMateriel> {
    return this.http.post<PretMateriel>(`${this.url}/prets/${id}/rendre/`, retour);
  }

  /** Photo d'état, au départ ou au retour. */
  photoPret(id: string, moment: 'DEPART' | 'RETOUR', photo: File): Observable<unknown> {
    const formulaire = new FormData();
    formulaire.append('pret', id);
    formulaire.append('moment_pret', moment);
    formulaire.append('fichier', photo);
    return this.http.post(`${environment.apiUrl}/documents/`, formulaire);
  }

  fichePret(id: string): Observable<Blob> {
    return this.http.get(`${this.url}/prets/${id}/fiche/`, { responseType: 'blob' });
  }

  // ── Demandes de transfert entre points ──────────────────────────────────────────────────
  transferts(point: string): Observable<DemandeTransfertStock[]> {
    return this.http.get<DemandeTransfertStock[]>(`${this.url}/transferts/`, { params: { point } });
  }

  /** Demandé par ceux qui tiennent le point d'arrivée ; rien ne part avant l'acceptation. */
  demanderTransfert(source: string, destination: string, item: string, quantite: number, message = ''): Observable<DemandeTransfertStock> {
    return this.http.post<DemandeTransfertStock>(`${this.url}/transferts/`, { source, destination, item, quantite, message });
  }

  repondreTransfert(id: string, geste: 'accepter' | 'refuser' | 'annuler', corps: { quantite?: number; reponse?: string } = {}): Observable<DemandeTransfertStock> {
    return this.http.post<DemandeTransfertStock>(`${this.url}/transferts/${id}/${geste}/`, corps);
  }

  // ── Disponibilité et réservations ───────────────────────────────────────────────────────
  /** « On l'a ? Où ? » — par mot, par besoin du catalogue, ou pour une demande d'habitant. */
  disponibilite(critere: { recherche?: string; item?: string; demande?: string }): Observable<DisponibiliteStock> {
    return this.http.get<DisponibiliteStock>(`${this.url}/disponibilite/`, { params: critere as Record<string, string> });
  }

  reservations(actives = true): Observable<ReservationStock[]> {
    return this.http.get<ReservationStock[]>(`${this.url}/reservations/`, { params: actives ? { actives: '1' } : {} });
  }

  reserver(reservation: { article: string; depot: string; quantite: number; pour?: string; demande?: string }): Observable<ReservationStock> {
    return this.http.post<ReservationStock>(`${this.url}/reservations/`, reservation);
  }

  /** `servir` : la personne vient chercher, le stock sort ; `liberer` : il est rendu aux autres. */
  cloreReservation(id: string, geste: 'servir' | 'liberer'): Observable<ReservationStock> {
    return this.http.post<ReservationStock>(`${this.url}/reservations/${id}/${geste}/`, {});
  }

  // ── Dotations types ─────────────────────────────────────────────────────────────────────
  lotsTypes(): Observable<LotTypeStock[]> { return this.http.get<LotTypeStock[]>(`${this.url}/lots-types/`); }

  enregistrerLot(lot: { id?: string; nom: string; description?: string; lignes: { article: string; quantite: number }[] }): Observable<LotTypeStock> {
    return lot.id ? this.http.patch<LotTypeStock>(`${this.url}/lots-types/${lot.id}/`, lot) : this.http.post<LotTypeStock>(`${this.url}/lots-types/`, lot);
  }

  verifierLot(id: string, depot: string): Observable<VerificationLot> {
    return this.http.get<VerificationLot>(`${this.url}/lots-types/${id}/verifier/`, { params: { depot } });
  }

  /** `sortir` : toute la dotation ou rien ; `rentrer` : ce qui revient (à défaut, tout). */
  gesteLot(id: string, geste: 'sortir' | 'rentrer', depot: string, quantites?: Record<string, number>): Observable<{ lignes: number }> {
    return this.http.post<{ lignes: number }>(`${this.url}/lots-types/${id}/${geste}/`, { depot, ...(quantites ? { quantites } : {}) });
  }

  // ── Appareils suivis à l'unité ──────────────────────────────────────────────────────────
  appareils(): Observable<AppareilStock[]> { return this.http.get<AppareilStock[]>(`${this.url}/appareils/`); }

  enregistrerAppareil(appareil: Partial<AppareilStock>): Observable<AppareilStock> {
    return appareil.id ? this.http.patch<AppareilStock>(`${this.url}/appareils/${appareil.id}/`, appareil)
      : this.http.post<AppareilStock>(`${this.url}/appareils/`, appareil);
  }

  /** Un contrôle fait : il repousse l'échéance. */
  controlerAppareil(id: string, conforme: boolean, commentaire = ''): Observable<AppareilStock> {
    return this.http.post<AppareilStock>(`${this.url}/appareils/${id}/controler/`, { conforme, commentaire });
  }
}
