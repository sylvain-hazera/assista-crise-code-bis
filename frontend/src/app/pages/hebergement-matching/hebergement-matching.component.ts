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
/** Temporaire ou longue durée : le critère qui décide si une offre peut servir à reloger une
 * famille ou seulement à la dépanner (`HebergementDetailsMixin.hebergement_duree`). */
export const DUREE_HEBERGEMENT_LABELS: Record<string, string> = {
  TEMPORAIRE: 'Temporaire', LONGUE_DUREE: 'Longue durée',
};

/** Champs numériques sur lesquels une tolérance +/- peut s'appliquer lors de la comparaison
 * d'une offre avec une demande sélectionnée — voir compareToDemande()/matchesTolerance(). */
const CHAMPS_TOLERANCE: (keyof Offer & keyof Request)[] = ['nombre_pieces', 'nombre_chambres', 'capacite_adultes', 'capacite_enfants'];

import { TelephonePipe } from '../../shared/pipes/telephone.pipe';

@Component({
  selector: 'app-hebergement-matching',
  standalone: true,
  imports: [TelephonePipe, CommonModule, FormsModule, RouterLink, MinimapComponent, TagSearchInputComponent],
  templateUrl: './hebergement-matching.component.html',
  styleUrl: './hebergement-matching.component.scss',
})
export class HebergementMatchingComponent implements OnInit {
  isLoading = true;
  errorMessage = '';
  team: Team | null = null;
  /** Les équipes de l'appelant, quand la page est ouverte depuis le MENU et non depuis une
   * équipe précise. Une page d'hébergement accessible seulement par le chemin
   * `/mon-equipe/<id>/hebergement` était introuvable pour qui ne savait pas déjà où aller. */
  mesEquipes: Team[] = [];
  /** Vrai quand l'appelant n'est dans aucune équipe : la page ne montre alors rien, et
   * l'écran DIT pourquoi au lieu de rester vide. */
  aucuneEquipe = false;

  private allDemandes: Request[] = [];
  private allOffres: Offer[] = [];

  readonly typeLogementLabels = TYPE_LOGEMENT_LABELS;
  readonly typeLoyerLabels = TYPE_LOYER_LABELS;
  readonly dureeLabels = DUREE_HEBERGEMENT_LABELS;
  readonly champsTolerance = CHAMPS_TOLERANCE;

  // ── Filtres communs (offres ET demandes) ────────────────────────
  filterTypeLogement = '';
  filterTypeLoyer = '';
  /** Temporaire / longue durée : demandé explicitement le 12/11/2026. C'est le critère qui
   * sépare « dépanner trois nuits » de « reloger le temps des travaux ». */
  filterDuree = '';
  filterAnimaux = false;
  filterJardin = false;
  filterPmr = false;
  /** Seuils numériques. Un nombre de chambres est une contrainte dure pour une famille : la
   * recherche par mots-clés ne la remplace pas. */
  filterChambresMin: number | null = null;
  filterPiecesMin: number | null = null;
  filterCapaciteMin: number | null = null;
  filterLoyerMax: number | null = null;
  /** Recherche libre, sur tout ce que la ligne affiche. */
  recherche = '';

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
  /** Fiche d'une DEMANDE : mêmes coordonnées à retrouver, côté famille cette fois. */
  selectedDemande: Request | null = null;
  detailEnCours = false;
  offerMessages: OfferMessage[] = [];
  newMessageContenu = '';
  sendingMessage = false;
  messagesError = '';

  /** L'œil : ouvre la fiche et VA LA CHERCHER au serveur.
   *
   * Ce n'est pas un détail d'implémentation. Les listes d'annonces arrivent **sans email ni
   * téléphone** (voir `core/tracabilite.py`) : les coordonnées ne viennent qu'avec la fiche
   * ouverte, dont la consultation est tracée objet par objet dans la main courante. Afficher
   * l'objet déjà chargé par la liste montrerait une fiche sans contact, et surtout
   * contournerait la trace qui permet de répondre à « qui a consulté les coordonnées de ces
   * gens ? ». */
  openOfferDetail(offer: Offer): void {
    this.selectedDemande = null;
    this.selectedOffer = offer;
    this.offerMessages = [];
    this.messagesError = '';
    this.detailEnCours = true;
    this.offerService.getById(offer.id).subscribe({
      next: (complete) => { this.selectedOffer = complete; this.detailEnCours = false; },
      // L'ancienne fiche reste affichée, sans coordonnées : mieux qu'un panneau vide.
      error: () => this.detailEnCours = false,
    });
    this.offerService.getMessages(offer.id).subscribe({
      next: (msgs) => this.offerMessages = msgs,
      error: () => this.messagesError = "Impossible de charger les messages.",
    });
  }

  openDemandeDetail(demande: Request): void {
    this.selectedOffer = null;
    this.selectedDemande = demande;
    this.detailEnCours = true;
    this.requestService.getById(demande.id).subscribe({
      next: (complete) => { this.selectedDemande = complete; this.detailEnCours = false; },
      error: () => this.detailEnCours = false,
    });
  }

  closeOfferDetail(): void {
    this.selectedOffer = null;
    this.selectedDemande = null;
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
    if (this.teamId) {
      this.loadAll();
      return;
    }
    // Ouverte depuis le MENU : on ne sait pas de quelle équipe il s'agit, on le demande.
    // Avant, la page n'existait qu'au bout de `/mon-equipe/<id>/hebergement` et restait
    // introuvable pour qui ne connaissait pas déjà le chemin (demande du 12/11/2026).
    this.teamService.mesEquipes().subscribe({
      next: (equipes) => {
        this.mesEquipes = (equipes ?? []).filter(e => e.actif !== false);
        if (!this.mesEquipes.length) {
          // Pas une erreur : un compte peut parfaitement n'être dans aucune équipe. L'écran
          // dit POURQUOI il n'y a rien, au lieu d'afficher un tableau vide ou un message
          // d'échec qui laisserait croire à une panne.
          this.aucuneEquipe = true;
          this.isLoading = false;
          return;
        }
        this.teamId = this.mesEquipes[0].id!;
        this.loadAll();
      },
      error: () => {
        this.errorMessage = "Impossible de charger vos équipes.";
        this.isLoading = false;
      },
    });
  }

  /** Changement d'équipe depuis le sélecteur : on recharge tout, filtres compris, parce que
   * les offres et les demandes sont celles des crises de CETTE équipe. */
  changerEquipe(id: string): void {
    if (!id || id === this.teamId) { return; }
    this.teamId = id;
    this.isLoading = true;
    this.selectedOffer = null;
    this.selectedDemande = null;
    this.demandeComparee = null;
    this.loadAll();
  }

  viderFiltres(): void {
    this.recherche = '';
    this.filterTypeLogement = '';
    this.filterTypeLoyer = '';
    this.filterDuree = '';
    this.filterAnimaux = false;
    this.filterJardin = false;
    this.filterPmr = false;
    this.filterChambresMin = null;
    this.filterPiecesMin = null;
    this.filterCapaciteMin = null;
    this.filterLoyerMax = null;
  }

  dureeLabel(item: Offer | Request): string {
    return item.hebergement_duree
      ? (this.dureeLabels[item.hebergement_duree] || item.hebergement_duree) : '—';
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
    if (this.filterDuree && item.hebergement_duree !== this.filterDuree) return false;
    if (this.filterAnimaux && !item.animaux_acceptes) return false;
    if (this.filterJardin && !item.jardin) return false;
    if (this.filterPmr && !item.pmr_compatible) return false;
    // Un seuil non renseigné sur la fiche NE PASSE PAS le filtre : « au moins 3 chambres » ne
    // peut pas être satisfait par une offre qui ne dit pas combien elle en a. L'inverse
    // enverrait une famille de cinq dans un studio.
    if (!this.auMoins(item.nombre_chambres, this.filterChambresMin)) return false;
    if (!this.auMoins(item.nombre_pieces, this.filterPiecesMin)) return false;
    if (!this.auMoins((item.capacite_adultes ?? 0) + (item.capacite_enfants ?? 0),
                      this.filterCapaciteMin)) return false;
    if (this.filterLoyerMax != null) {
      const loyer = item.loyer_montant_min ?? item.loyer_montant_max;
      // Une offre gratuite passe toujours : elle n'a pas de montant, et l'écarter d'un filtre
      // « loyer maximum » serait exactement l'inverse de ce qu'on cherche.
      if (item.type_loyer !== 'GRATUIT' && (loyer == null || loyer > this.filterLoyerMax)) {
        return false;
      }
    }
    if (this.recherche.trim() && !this.texteDe(item).includes(
          this.recherche.trim().toLowerCase())) return false;
    return true;
  }

  private auMoins(valeur: number | null | undefined, seuil: number | null): boolean {
    if (seuil == null) return true;
    return valeur != null && valeur >= seuil;
  }

  /** Tout ce sur quoi la recherche libre porte : on cherche une annonce par son titre, sa
   * commune ou son texte, sans avoir à choisir un champ d'abord. */
  private texteDe(item: Offer | Request): string {
    const fiche = item as unknown as Record<string, unknown>;
    return [item.title, item.description, fiche['commune_nom'], fiche['city'],
            fiche['address']]
      .filter(Boolean).join(' ').toLowerCase();
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
