import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import * as turf from '@turf/turf';

import { TeamService } from '../../services/team.service';
import { OfferService } from '../../services/offer.service';
import { RequestService } from '../../services/request.service';
import { LocationService, Commune } from '../../services/location.service';

import { Team } from '../../shared/models/team.model';
import { Offer } from '../../shared/models/offer.model';
import { Request } from '../../shared/models/request.model';
import { OfferMessage } from '../../shared/models/offer-message.model';

import { MinimapComponent, MinimapPointInteret } from '../../shared/components/common/minimap/minimap.component';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';

export const TYPE_LOGEMENT_LABELS: Record<string, string> = {
  MAISON: 'Maison', APPARTEMENT: 'Appartement', STUDIO: 'Studio', COLOCATION: 'Colocation', CHAMBRE: 'Chambre',
};
export const TYPE_LOYER_LABELS: Record<string, string> = {
  GRATUIT: 'Gratuit', NEGOCIE: 'Loyer négocié', MARCHE: 'Prix du marché',
};

/** Champs numériques sur lesquels une tolérance +/- peut s'appliquer lors de la comparaison
 * d'une offre avec une demande sélectionnée — voir compareToDemande()/matchesTolerance(). */
const CHAMPS_TOLERANCE: (keyof Offer & keyof Request)[] = ['nombre_pieces', 'nombre_chambres', 'capacite_adultes', 'capacite_enfants'];

@Component({
  selector: 'app-hebergement-matching',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, MinimapComponent, TagSearchInputComponent],
  templateUrl: './hebergement-matching.component.html',
  styleUrl: './hebergement-matching.component.scss',
})
export class HebergementMatchingComponent implements OnInit {
  isLoading = true;
  errorMessage = '';
  team: Team | null = null;

  private allDemandes: Request[] = [];
  private allOffres: Offer[] = [];

  readonly typeLogementLabels = TYPE_LOGEMENT_LABELS;
  readonly typeLoyerLabels = TYPE_LOYER_LABELS;
  readonly champsTolerance = CHAMPS_TOLERANCE;

  // ── Filtres communs (offres ET demandes) ────────────────────────
  filterTypeLogement = '';
  filterTypeLoyer = '';
  filterAnimaux = false;
  filterJardin = false;
  filterPmr = false;

  // ── Filtre zone (offres uniquement) : communes + rayon ──────────
  zoneCommunes: Commune[] = [];
  zoneRayonKm: number | null = null;
  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);
  private zoneCentroids: { latitude: number; longitude: number }[] = [];

  addZoneCommune(commune: Commune): void {
    if (this.zoneCommunes.some(c => c.code === commune.code)) return;
    this.zoneCommunes = [...this.zoneCommunes, commune];
    this.locationService.getCommuneCentre(commune.code).subscribe({
      next: (centre) => this.zoneCentroids = [...this.zoneCentroids, centre],
      error: () => {},
    });
  }

  removeZoneCommune(code: string): void {
    const idx = this.zoneCommunes.findIndex(c => c.code === code);
    if (idx === -1) return;
    this.zoneCommunes = this.zoneCommunes.filter(c => c.code !== code);
    this.zoneCentroids.splice(idx, 1);
  }

  // ── Comparaison à tolérance +/- avec une demande sélectionnée (offres uniquement) ──
  demandeComparee: Request | null = null;
  tolerance = 1;

  compareToDemande(demande: Request): void {
    this.demandeComparee = this.demandeComparee?.id === demande.id ? null : demande;
  }

  // ── Tri (indépendant par colonne) ────────────────────────────────
  sortFieldOffres = 'created_at';
  sortAscOffres = false;
  sortFieldDemandes = 'created_at';
  sortAscDemandes = false;

  setSortOffres(field: string): void {
    if (this.sortFieldOffres === field) this.sortAscOffres = !this.sortAscOffres;
    else { this.sortFieldOffres = field; this.sortAscOffres = true; }
  }

  setSortDemandes(field: string): void {
    if (this.sortFieldDemandes === field) this.sortAscDemandes = !this.sortAscDemandes;
    else { this.sortFieldDemandes = field; this.sortAscDemandes = true; }
  }

  // ── Détail offre + messagerie ────────────────────────────────────
  selectedOffer: Offer | null = null;
  offerMessages: OfferMessage[] = [];
  newMessageContenu = '';
  sendingMessage = false;
  messagesError = '';

  openOfferDetail(offer: Offer): void {
    this.selectedOffer = offer;
    this.offerMessages = [];
    this.messagesError = '';
    this.offerService.getMessages(offer.id).subscribe({
      next: (msgs) => this.offerMessages = msgs,
      error: () => this.messagesError = "Impossible de charger les messages.",
    });
  }

  closeOfferDetail(): void {
    this.selectedOffer = null;
  }

  sendMessage(): void {
    if (!this.selectedOffer || !this.newMessageContenu.trim()) return;
    this.sendingMessage = true;
    this.offerService.sendMessage(this.selectedOffer.id, this.newMessageContenu.trim()).subscribe({
      next: (msg) => {
        this.offerMessages = [...this.offerMessages, msg];
        this.newMessageContenu = '';
        this.sendingMessage = false;
      },
      error: () => { this.messagesError = "Erreur lors de l'envoi du message."; this.sendingMessage = false; },
    });
  }

  pointsInteret: MinimapPointInteret[] = [];
  centerLatitude = 46.2276;
  centerLongitude = 2.2137;

  private teamId = '';

  constructor(
    private route: ActivatedRoute,
    private teamService: TeamService,
    private offerService: OfferService,
    private requestService: RequestService,
    private locationService: LocationService,
  ) {}

  ngOnInit(): void {
    this.teamId = this.route.snapshot.params['id'];
    if (!this.teamId) {
      this.errorMessage = 'Équipe introuvable.';
      this.isLoading = false;
      return;
    }
    this.loadAll();
  }

  private loadAll(): void {
    forkJoin({
      team: this.teamService.getById(this.teamId),
      // exclude_type=Bénévolat : hors-sujet pour un matching d'hébergement (voir
      // ReportingComponent.loadAll pour le même motif).
      offers: this.offerService.getAll({ exclude_type: 'Bénévolat' }),
      requests: this.requestService.getAll(),
      requestTypes: this.requestService.getTypes(),
    }).subscribe({
      next: ({ team, offers, requests, requestTypes }) => {
        this.team = team;
        const hebergementTypeId = requestTypes.find(t => t.type === 'Hébergement')?.id;
        const crisisIds = new Set(team.assigned_crisis_ids || []);

        this.allOffres = offers.filter(o =>
          o.offer_type_nom === 'Hébergement' && o.actif !== false && !!o.crisis && crisisIds.has(o.crisis)
        );
        this.allDemandes = requests.filter(r =>
          r.request_type === hebergementTypeId && r.actif !== false && !!r.crisis && crisisIds.has(r.crisis)
        );

        this.pointsInteret = this.allOffres
          .filter(o => o.latitude != null && o.longitude != null)
          .map(o => ({ latitude: o.latitude!, longitude: o.longitude!, label: `${o.title} (${o.first_name_offer} ${o.last_name_offer})` }));
        if (team.commune_centre?.latitude != null && team.commune_centre?.longitude != null) {
          this.centerLatitude = team.commune_centre.latitude;
          this.centerLongitude = team.commune_centre.longitude;
        } else if (this.pointsInteret.length > 0) {
          this.centerLatitude = this.pointsInteret[0].latitude;
          this.centerLongitude = this.pointsInteret[0].longitude;
        }

        this.isLoading = false;
      },
      error: () => {
        this.errorMessage = "Impossible de charger cette équipe : elle n'existe pas ou vous n'y avez plus accès.";
        this.isLoading = false;
      },
    });
  }

  private matchesCommonFilters(item: Offer | Request): boolean {
    if (this.filterTypeLogement && item.type_logement !== this.filterTypeLogement) return false;
    if (this.filterTypeLoyer && item.type_loyer !== this.filterTypeLoyer) return false;
    if (this.filterAnimaux && !item.animaux_acceptes) return false;
    if (this.filterJardin && !item.jardin) return false;
    if (this.filterPmr && !item.pmr_compatible) return false;
    return true;
  }

  private matchesZone(offer: Offer): boolean {
    if (this.zoneCentroids.length === 0) return true;
    if (offer.latitude == null || offer.longitude == null) return false;
    const rayon = this.zoneRayonKm ?? 0;
    return this.zoneCentroids.some(centre => {
      const distance = turf.distance(
        [centre.longitude, centre.latitude],
        [offer.longitude!, offer.latitude!],
        { units: 'kilometers' }
      );
      return distance <= rayon;
    });
  }

  /** Une offre correspond à la demande comparée si chaque critère numérique renseigné sur la
   * demande reste dans la fourchette [valeur - tolérance ; valeur + tolérance] côté offre — la
   * demande elle-même n'est jamais modifiée, seul le filtre appliqué aux offres change. */
  private matchesTolerance(offer: Offer): boolean {
    if (!this.demandeComparee) return true;
    return this.champsTolerance.every(champ => {
      const valeurDemande = this.demandeComparee![champ] as number | null | undefined;
      if (valeurDemande == null) return true;
      const valeurOffre = offer[champ] as number | null | undefined;
      if (valeurOffre == null) return false;
      return Math.abs(valeurOffre - valeurDemande) <= this.tolerance;
    });
  }

  get offresAffichees(): Offer[] {
    const filtered = this.allOffres.filter(o =>
      this.matchesCommonFilters(o) && this.matchesZone(o) && this.matchesTolerance(o)
    );
    return this.sortRows(filtered, this.sortFieldOffres, this.sortAscOffres);
  }

  get demandesAffichees(): Request[] {
    const filtered = this.allDemandes.filter(r => this.matchesCommonFilters(r));
    return this.sortRows(filtered, this.sortFieldDemandes, this.sortAscDemandes);
  }

  private sortRows<T extends Record<string, any>>(rows: T[], field: string, asc: boolean): T[] {
    return [...rows].sort((a, b) => {
      const va = a[field];
      const vb = b[field];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (va < vb) return asc ? -1 : 1;
      if (va > vb) return asc ? 1 : -1;
      return 0;
    });
  }

  logementLabel(item: Offer | Request): string {
    return item.type_logement ? (this.typeLogementLabels[item.type_logement] || item.type_logement) : '—';
  }

  loyerLabel(item: Offer | Request): string {
    return item.type_loyer ? (this.typeLoyerLabels[item.type_loyer] || item.type_loyer) : '—';
  }
}
