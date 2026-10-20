import { Component, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';

import { HabitationCarteComponent } from '../habitation-carte/habitation-carte.component';
import { HabitationFicheComponent } from '../habitation-fiche/habitation-fiche.component';
import { HabitationService, HabitationFiltres } from '../../../services/habitation.service';
import { Habitation, LABELS_STATUT_EVALUATION, LABELS_STATUT_CHANTIER } from '../../../shared/models/habitation.model';
import { AuthService } from '../../../auth/services/auth.service';
import { CrisisService } from '../../../services/crisis.service';
import { Crisis } from '../../../shared/models/crisis.model';
import { ZoneService } from '../../../services/zone.service';
import { Zone } from '../../../shared/models/zone.model';
import { LocationService, Commune } from '../../../services/location.service';
import { TagSearchInputComponent } from '../../../shared/components/common/tag-search-input/tag-search-input.component';
import { ModuleDegatsCriseService } from '../../../services/module-degats.service';
import { ModuleDegatsCrise } from '../../../shared/models/habitation.model';

type Vue = 'carte' | 'liste';

/** Page "Référencement des dégâts" — carte + vue de suivi (liste avec recherche/filtre
 * multicritère, regroupement par zone) pour une commune/zone sinistrée. Accessible sans compte
 * (consultation publique + dépôt d'un rattachement propriétaire/locataire) ; les actions de
 * gestion (créer/évaluer/importer/accepter un rattachement) restent conditionnées côté backend
 * à une délégation (voir Habitation.peut_gerer, HabitationViewSet). */
@Component({
  selector: 'app-habitations-page',
  standalone: true,
  imports: [CommonModule, FormsModule, HabitationCarteComponent, HabitationFicheComponent, TagSearchInputComponent],
  templateUrl: './habitations-page.component.html',
  styleUrl: './habitations-page.component.scss',
})
export class HabitationsPageComponent implements OnInit {
  @ViewChild(HabitationCarteComponent) carte?: HabitationCarteComponent;

  vue: Vue = 'carte';
  habitations: Habitation[] = [];
  chargement = true;

  filtres: HabitationFiltres = {};
  labelsEvaluation = LABELS_STATUT_EVALUATION;
  labelsChantier = LABELS_STATUT_CHANTIER;

  habitationSelectionnee: Habitation | null = null;

  panneauImportOuvert = false;
  fichierImport: File | null = null;
  mappingImport: Record<string, string> = {};
  colonnesFichier: string[] = [];
  resultatImport: { crees: number; erreurs: { ligne: number; message: string }[] } | null = null;
  importEnCours = false;

  // Estimation automatique via la BAN (Phase 2) -- toujours plafonnée à UNE commune (voir
  // HabitationViewSet.estimation_ban), une crise sélectionnée ne fait que restreindre encore
  // le résultat si elle a une zone dessinée, jamais l'élargir à plusieurs communes.
  panneauEstimationOuvert = false;
  communeEstimation = '';
  communeEstimationLabel = '';
  criseEstimationId = '';
  // Zone nommée (ex: "Quartier Nord") pour restreindre le scan à l'intérieur de la commune
  // sélectionnée -- distincte de la zone dessinée de la crise, voir habitations.perimetre_scan.
  zoneEstimationId = '';
  georisquesEstimation = '';   // filtre optionnel : zones de débordement officielles
  readonly scenariosDebordement = [
    { valeur: 'ALEA_SYNT_01_01FOR_FXX', libelle: 'Débordement fréquent (décennal)' },
    { valeur: 'ALEA_SYNT_01_02MOY_FXX', libelle: 'Débordement moyen (centennal, réf. PPRI)' },
    { valeur: 'ALEA_SYNT_01_04FAI_FXX', libelle: 'Débordement rare (millénal)' },
  ];
  crises: Crisis[] = [];
  zones: Zone[] = [];
  estimationEnCours = false;
  resultatEstimation: { creees: number; adresses_trouvees: number; voies_totales: number; voies_en_echec: number; filtre_georisques?: string | null } | null = null;
  erreurEstimation = '';

  communeSearchFn = (q: string) => this.locationService.searchCommunesByName(q);

  // Activation du module (désactivé par défaut, voir ModuleDegatsCrise.__doc__) : une mairie/
  // EPCI choisit une crise et, optionnellement, une zone restreignant où les points peuvent
  // être chargés -- ne montre que le module de SON institution (une ligne existe par couple
  // crise/institution).
  panneauModuleOuvert = false;
  moduleCriseId = '';
  moduleZoneId = '';
  moduleCourant: ModuleDegatsCrise | null = null;
  moduleChargement = false;
  moduleEnCours = false;

  // Bandeau public : si la crise consultée (filtres.crise) n'a de module actif pour AUCUNE
  // institution, la page reste consultable mais on le signale plutôt que de laisser une carte
  // vide sans explication.
  moduleActifPourCriseFiltree: boolean | null = null;

  constructor(
    private habitationService: HabitationService,
    private crisisService: CrisisService,
    private zoneService: ZoneService,
    private locationService: LocationService,
    private moduleDegatsService: ModuleDegatsCriseService,
    private route: ActivatedRoute,
    public authService: AuthService,
  ) {}

  ngOnInit(): void {
    const communeCode = this.route.snapshot.queryParamMap.get('commune');
    if (communeCode) this.filtres.commune_code = communeCode;
    const criseId = this.route.snapshot.queryParamMap.get('crise');
    if (criseId) this.filtres.crise = criseId;
    this.charger();
  }

  changerVue(v: Vue): void {
    this.vue = v;
  }

  charger(): void {
    this.chargement = true;
    this.habitationService.getAll(this.filtres).subscribe({
      next: (h) => { this.habitations = h; this.chargement = false; this.carte?.recharger(this.filtres); },
      error: () => { this.chargement = false; },
    });
    this.verifierModuleCriseFiltree();
  }

  private verifierModuleCriseFiltree(): void {
    if (!this.filtres.crise) { this.moduleActifPourCriseFiltree = null; return; }
    this.moduleDegatsService.getPourCrise(this.filtres.crise).subscribe({
      next: (modules) => { this.moduleActifPourCriseFiltree = modules.some(m => m.actif); },
      error: () => { this.moduleActifPourCriseFiltree = null; },
    });
  }

  appliquerFiltres(): void {
    this.charger();
  }

  ouvrirFiche(h: Habitation): void {
    this.habitationSelectionnee = h;
  }

  fermerFiche(): void {
    this.habitationSelectionnee = null;
  }

  surMiseAJour(h: Habitation): void {
    const idx = this.habitations.findIndex(x => x.id === h.id);
    if (idx >= 0) this.habitations[idx] = h;
    this.habitationSelectionnee = h;
    this.carte?.recharger(this.filtres);
  }

  // Regroupement par zone pour la vue liste (habitations sans zone regroupées à part) — évite
  // de dépendre d'un tri serveur, la liste chargée tient largement en mémoire pour une commune.
  get groupesParZone(): { nom: string; habitations: Habitation[] }[] {
    const groupes = new Map<string, Habitation[]>();
    for (const h of this.habitations) {
      const cle = h.zone_nom || 'Sans zone';
      if (!groupes.has(cle)) groupes.set(cle, []);
      groupes.get(cle)!.push(h);
    }
    // Trié par adresse au sein de chaque zone -- demandé explicitement pour la validation des
    // requêtes de rattachement (tableau institution "vue de suivi").
    return Array.from(groupes.entries()).map(([nom, habitations]) => ({
      nom, habitations: [...habitations].sort((a, b) => a.adresse.localeCompare(b.adresse)),
    }));
  }

  ouvrirImport(): void {
    this.panneauImportOuvert = true;
    this.resultatImport = null;
  }

  onFichierImportChoisi(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.fichierImport = input.files?.[0] || null;
    // Pas d'aperçu de colonnes ici (contrairement à l'import personnel communal) : le mapping
    // reste simple (adresse/latitude/longitude/parcelle/commune), l'utilisateur les associe à
    // l'œil vu le faible nombre de colonnes cibles, pas besoin d'un sélecteur dynamique par
    // en-tête détecté.
  }

  lancerImport(): void {
    if (!this.fichierImport) return;
    this.importEnCours = true;
    this.habitationService.importerCsv(this.fichierImport, this.mappingImport).subscribe({
      next: (resultat) => {
        this.importEnCours = false;
        this.resultatImport = resultat;
        this.fichierImport = null;
        this.charger();
      },
      error: () => { this.importEnCours = false; },
    });
  }

  ouvrirEstimation(): void {
    this.panneauEstimationOuvert = true;
    this.resultatEstimation = null;
    this.erreurEstimation = '';
    this.communeEstimation = this.filtres.commune_code || '';
    this.communeEstimationLabel = '';
    this.zoneEstimationId = '';
    if (this.crises.length === 0) {
      this.crisisService.getAll().subscribe(c => this.crises = c);
    }
    if (this.zones.length === 0) {
      // Sans filtre institution : le backend restreint déjà aux zones des institutions de
      // l'utilisateur courant (voir ZoneViewSet.get_queryset), même portée que le reste de la page.
      this.zoneService.getAll().subscribe(z => this.zones = z);
    }
  }

  surCommuneChoisie(commune: Commune): void {
    this.communeEstimation = commune.code;
    this.communeEstimationLabel = commune.codePostal ? `${commune.name} (${commune.codePostal})` : commune.name;
  }

  lancerEstimation(): void {
    if (!this.communeEstimation.trim()) return;
    this.estimationEnCours = true;
    this.resultatEstimation = null;
    this.erreurEstimation = '';
    this.habitationService.estimationBan(
      this.communeEstimation.trim(), this.criseEstimationId || undefined, this.zoneEstimationId || undefined,
      this.georisquesEstimation || undefined,
    ).subscribe({
      next: (resultat) => {
        this.estimationEnCours = false;
        this.resultatEstimation = resultat;
        this.charger();
      },
      error: (err) => {
        this.estimationEnCours = false;
        this.erreurEstimation = err.error?.error || 'Une erreur est survenue.';
      },
    });
  }

  ouvrirModule(): void {
    this.panneauModuleOuvert = true;
    this.moduleCriseId = '';
    this.moduleZoneId = '';
    this.moduleCourant = null;
    if (this.crises.length === 0) this.crisisService.getAll().subscribe(c => this.crises = c);
    if (this.zones.length === 0) this.zoneService.getAll().subscribe(z => this.zones = z);
  }

  changerCriseModule(): void {
    this.moduleCourant = null;
    this.moduleZoneId = '';
    if (!this.moduleCriseId) return;
    this.moduleChargement = true;
    const institutionId = this.authService.getCurrentUser()?.institution_id;
    this.moduleDegatsService.getPourCrise(this.moduleCriseId).subscribe({
      next: (modules) => {
        this.moduleChargement = false;
        this.moduleCourant = modules.find(m => m.institution === institutionId) || null;
        this.moduleZoneId = this.moduleCourant?.zone || '';
      },
      error: () => { this.moduleChargement = false; },
    });
  }

  activerModule(): void {
    if (!this.moduleCriseId) return;
    this.moduleEnCours = true;
    this.moduleDegatsService.activer({ crise: this.moduleCriseId, zone: this.moduleZoneId || null }).subscribe({
      next: (module) => { this.moduleEnCours = false; this.moduleCourant = module; this.charger(); },
      error: () => { this.moduleEnCours = false; },
    });
  }

  basculerModule(): void {
    if (!this.moduleCourant) return;
    this.moduleEnCours = true;
    this.moduleDegatsService.modifier(this.moduleCourant.id, { actif: !this.moduleCourant.actif }).subscribe({
      next: (module) => { this.moduleEnCours = false; this.moduleCourant = module; this.charger(); },
      error: () => { this.moduleEnCours = false; },
    });
  }

  changerZoneModule(): void {
    if (!this.moduleCourant) return;
    this.moduleDegatsService.modifier(this.moduleCourant.id, { zone: this.moduleZoneId || null }).subscribe(module => {
      this.moduleCourant = module;
    });
  }

  telechargerExemple(): void {
    this.habitationService.telechargerExempleCsv().subscribe(blob => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'exemple-habitations.csv';
      a.click();
      URL.revokeObjectURL(url);
    });
  }
}
