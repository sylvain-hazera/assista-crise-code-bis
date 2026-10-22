import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { BesoinCompetenceService } from '../../services/besoin-competence.service';
import { BesoinMaterielService } from '../../services/besoin-materiel.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { MaterielCatalogueService } from '../../services/materiel-catalogue.service';
import { BesoinCompetence } from '../../shared/models/besoin-competence.model';
import { BesoinMateriel } from '../../shared/models/besoin-materiel.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { MaterielCatalogue } from '../../shared/models/materiel-catalogue.model';
import { TagSearchInputComponent } from '../../shared/components/common/tag-search-input/tag-search-input.component';
import { AxeType, CorrespondanceType, CorrespondanceTypeService } from '../../services/correspondance-type.service';
import { RequestService } from '../../services/request.service';
import { InformationService } from '../../services/information.service';
import { AuthService } from '../../auth/services/auth.service';
import { UserRole } from '../../shared/models/user.model';

@Component({
  selector: 'app-besoins-competences',
  standalone: true,
  imports: [CommonModule, FormsModule, TagSearchInputComponent],
  templateUrl: './besoins-competences.component.html'
})
export class BesoinsCompetencesComponent implements OnInit {

  // Premier maillon : type de demande / de signalement → besoin (22/10/2026 : aucun écran
  // jusqu'ici, d'où des types entiers -- Hébergement, Transport... -- sans compétence).
  typesParAxe: Record<AxeType, { id: string; type: string }[]> = { demande: [], signalement: [] };
  correspondancesType: Record<AxeType, CorrespondanceType[]> = { demande: [], signalement: [] };
  choixType: Record<AxeType, string | null> = { demande: null, signalement: null };
  choixBesoin: Record<AxeType, string | null> = { demande: null, signalement: null };
  readonly axes: { axe: AxeType; titre: string }[] = [
    { axe: 'demande', titre: 'Type de demande → Besoin' },
    { axe: 'signalement', titre: 'Type de signalement → Besoin' },
  ];

  correspondancesCompetence: BesoinCompetence[] = [];
  correspondancesMateriel: BesoinMateriel[] = [];
  besoins: Besoin[] = [];

  selectedBesoinIdCompetence: string | null = null;
  selectedCompetence: Competence | null = null;

  selectedBesoinIdMateriel: string | null = null;
  selectedMateriel: MaterielCatalogue | null = null;

  constructor(
    private service: BesoinCompetenceService,
    private materielService: BesoinMaterielService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private materielCatalogueService: MaterielCatalogueService,
    private correspondanceTypeService: CorrespondanceTypeService,
    private requestService: RequestService,
    private informationService: InformationService,
    private authService: AuthService,
  ) {}

  /** Modification réservée aux administrateurs (rôle effectif), lecture pour les autres. */
  get estAdmin(): boolean {
    return this.authService.getEffectiveRole() === UserRole.ADMIN;
  }

  ngOnInit(): void {
    this.load();
    this.requestService.getTypes().subscribe(types => { this.typesParAxe.demande = types; });
    this.informationService.getTypes().subscribe(types => { this.typesParAxe.signalement = types; });
    this.besoinService.getAll().subscribe(data => {
      this.besoins = data;
    });
  }

  load(): void {
    for (const { axe } of this.axes) {
      this.correspondanceTypeService.getAll(axe).subscribe(data => { this.correspondancesType[axe] = data; });
    }
    this.service.getAll().subscribe(data => {
      this.correspondancesCompetence = data;
    });
    this.materielService.getAll().subscribe(data => {
      this.correspondancesMateriel = data;
    });
  }

  /** Besoins pour lesquels une correspondance compétence a du sens — non qualifiés (nature
   * absente) inclus, pour ne pas bloquer avant qualification via la page Besoins. */
  besoinsPourCompetence(): Besoin[] {
    return this.besoins.filter(b => !b.nature || b.nature === 'COMPETENCE' || b.nature === 'MIXTE');
  }

  besoinsPourMateriel(): Besoin[] {
    return this.besoins.filter(b => !b.nature || b.nature === 'MATERIEL' || b.nature === 'MIXTE');
  }

  competenceSearchFn = (q: string) => this.competenceService.search(q);
  competenceCreateFn = (nom: string) => this.competenceService.create({ nom });

  materielSearchFn = (q: string) => this.materielCatalogueService.search(q);
  materielCreateFn = (nom: string) => this.materielCatalogueService.create({ nom });

  onCompetenceSelected(item: Competence): void {
    this.selectedCompetence = item;
  }

  onMaterielSelected(item: MaterielCatalogue): void {
    this.selectedMateriel = item;
  }

  submitCompetence(): void {
    if (!this.selectedBesoinIdCompetence || !this.selectedCompetence) {
      return;
    }
    this.service.create(this.selectedBesoinIdCompetence, this.selectedCompetence.id).subscribe(() => {
      this.selectedBesoinIdCompetence = null;
      this.selectedCompetence = null;
      this.load();
    });
  }

  submitMateriel(): void {
    if (!this.selectedBesoinIdMateriel || !this.selectedMateriel) {
      return;
    }
    this.materielService.create(this.selectedBesoinIdMateriel, this.selectedMateriel.id).subscribe(() => {
      this.selectedBesoinIdMateriel = null;
      this.selectedMateriel = null;
      this.load();
    });
  }

  nomType(axe: AxeType, c: CorrespondanceType): string {
    return (axe === 'demande' ? c.request_type_nom : c.information_type_nom) || '';
  }

  submitType(axe: AxeType): void {
    const typeId = this.choixType[axe], besoinId = this.choixBesoin[axe];
    if (!typeId || !besoinId) return;
    this.correspondanceTypeService.create(axe, typeId, besoinId).subscribe({
      next: () => { this.choixType[axe] = null; this.choixBesoin[axe] = null; this.load(); },
      error: (err) => alert(err?.error?.detail || err?.error?.non_field_errors?.[0] || "Impossible d'ajouter cette correspondance."),
    });
  }

  deleteType(axe: AxeType, id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) return;
    this.correspondanceTypeService.delete(axe, id).subscribe(() => this.load());
  }

  // ── À compléter : ce qui empêche un dossier d'avoir une compétence ────────────────

  typesSansBesoin(axe: AxeType): string[] {
    const relies = new Set(this.correspondancesType[axe].map(c => axe === 'demande' ? c.request_type : c.information_type));
    return this.typesParAxe[axe].filter(t => !relies.has(t.id)).map(t => t.type).sort();
  }

  /** Besoins atteints par un type mais reliés à aucune compétence (et, pour un besoin de
   * matériel, à aucun matériel non plus). */
  besoinsSansSuite(): string[] {
    const utilises = new Set([...this.correspondancesType.demande, ...this.correspondancesType.signalement].map(c => c.besoin));
    const avecCompetence = new Set(this.correspondancesCompetence.map(c => c.besoin));
    const avecMateriel = new Set(this.correspondancesMateriel.map(c => c.besoin));
    return this.besoins
      .filter(b => utilises.has(b.id) && !avecCompetence.has(b.id) && !(b.nature === 'MATERIEL' && avecMateriel.has(b.id)))
      .map(b => b.nom).sort();
  }

  deleteCompetence(id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) {
      return;
    }
    this.service.delete(id).subscribe(() => this.load());
  }

  deleteMateriel(id: string): void {
    if (!confirm('Supprimer cette correspondance ?')) {
      return;
    }
    this.materielService.delete(id).subscribe(() => this.load());
  }
}
