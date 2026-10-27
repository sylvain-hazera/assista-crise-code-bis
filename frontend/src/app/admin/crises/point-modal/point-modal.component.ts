import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { PointOperationnelService } from '../../../services/point-operationnel.service';
import { CompetenceService } from '../../../services/competence.service';
import { TeamService } from '../../../services/team.service';
import { UserService } from '../../../services/user.service';
import { CrisisService } from '../../../services/crisis.service';
import { AuthService } from '../../../auth/services/auth.service';
import { PointOperationnel, PointType } from '../../../shared/models/point-operationnel.model';
import { Institution } from '../../../shared/models/institution.model';
import { Competence } from '../../../shared/models/competence.model';
import { Team } from '../../../shared/models/team.model';
import { User } from '../../../shared/models/user.model';
import { Crisis } from '../../../shared/models/crisis.model';
import { AddressResult } from '../../../shared/models/address-result.model';
import { AddressPickerComponent } from '../../../shared/components/common/address-picker/address-picker.component';
import { PointPickerComponent } from '../../../shared/components/common/point-picker/point-picker.component';
import { PointEquipeModalComponent } from '../point-equipe-modal/point-equipe-modal.component';
import { PointInventaireModalComponent } from '../point-inventaire-modal/point-inventaire-modal.component';
import { PointSecretariatModalComponent } from '../point-secretariat-modal/point-secretariat-modal.component';
import { PointVueOperationnelleModalComponent } from '../point-vue-operationnelle-modal/point-vue-operationnelle-modal.component';

/** Modale de création/édition d'un point opérationnel (composant dédié : chaque volet y ajoute
 * sa section). */
@Component({
  selector: 'app-point-modal',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, FormsModule, AddressPickerComponent, PointPickerComponent, PointEquipeModalComponent, PointInventaireModalComponent, PointSecretariatModalComponent, PointVueOperationnelleModalComponent],
  templateUrl: './point-modal.component.html',
  styleUrl: './point-modal.component.scss'
})
export class PointModalComponent implements OnChanges {
  // Facultatif : un point créé depuis une équipe n'a pas forcément de crise.
  @Input() crisisId: string | null = null;
  @Input({ required: true }) pointTypes: PointType[] = [];
  @Input({ required: true }) selectableInstitutions: Institution[] = [];
  @Input() isAdmin = false;
  @Input() point: PointOperationnel | null = null; // null = création
  /** Équipe pré-sélectionnée à la création, modifiable. */
  @Input() defaultEquipeId: string | null = null;

  @Output() saved = new EventEmitter<PointOperationnel>();
  @Output() closed = new EventEmitter<void>();
  /** Mise à jour sans fermer la modale (le parent rafraîchit sa liste), contrairement à `saved`. */
  @Output() pointUpdated = new EventEmitter<PointOperationnel>();

  form!: FormGroup;
  latitude: number | null = null;
  longitude: number | null = null;
  saving = false;
  errorMessage = '';
  selectedCompetences: { id: string; nom: string }[] = [];
  teams: Team[] = [];
  users: User[] = [];
  crises: Crisis[] = [];
  allCompetences: Competence[] = [];
  competenceSelectValue = '';
  competenceAutreLibelle = '';
  myInstitutionId: string | null = null;
  equipeModalOpen = false;
  inventaireModalOpen = false;
  secretariatModalOpen = false;
  vueOperationnelleModalOpen = false;

  // Équipes/responsables supplémentaires (equipes_gestion, equipes_ravitaillement, responsables),
  // distincts du champ historique `equipe`.
  selectedEquipesGestion: string[] = [];
  selectedEquipesRavitaillement: string[] = [];
  selectedResponsables: string[] = [];

  constructor(
    private fb: FormBuilder,
    private pointService: PointOperationnelService,
    private competenceService: CompetenceService,
    private teamService: TeamService,
    private userService: UserService,
    private crisisService: CrisisService,
    private authService: AuthService,
    private router: Router,
  ) {
    this.buildForm();
    this.myInstitutionId = this.authService.getCurrentUser()?.institution_id ?? null;
    this.teamService.getAll().subscribe(teams => {
      this.teams = teams;
      this.refreshCandidateUsers();
    });
    this.competenceService.getAll().subscribe(c => this.allCompetences = c);
    this.crisisService.getAll().subscribe(crises => {
      this.crises = crises;
      // La liste arrive APRÈS buildForm() : sans aucune crise à proposer, exiger un
      // rattachement serait une impasse (le select resterait vide et le formulaire invalide).
      if (!this.isEdit && !this.crisisId && !crises.length) {
        this.choisirRattachement('avance');
      }
    });
  }

  /** Candidats responsables : membres de l'institution du point (via son équipe) ou de sa
   * déléguée, jamais celle du compte connecté, même pour un admin. Sans équipe, aucun candidat. */
  private refreshCandidateUsers(): void {
    const institutionIds = this.pointInstitutionIds;

    if (institutionIds.length === 0) {
      this.users = [];
      this.ensureAssignedUsersPresent();
      return;
    }

    this.userService.getAll({ institution: institutionIds }).subscribe(users => {
      this.users = users;
      this.ensureAssignedUsersPresent();
    });
  }

  /** Institutions du point : celle de l'équipe responsable + sa déléguée, ou à défaut celle
   * choisie dans le champ Institution. */
  private get pointInstitutionIds(): string[] {
    const equipeId = this.form?.get('equipe')?.value ?? this.point?.equipe ?? this.defaultEquipeId;
    const equipe = this.teams.find(t => t.id === equipeId);
    if (equipe) {
      return [equipe.institution, equipe.institution_delegataire].filter((id): id is string => !!id);
    }
    const institutionId = this.form?.get('institution')?.value ?? this.myInstitutionId;
    return institutionId ? [institutionId] : [];
  }

  // Utilisateurs déjà rattachés mais hors de la liste scopée : récupérés pour rester affichés.
  private ensureAssignedUsersPresent(): void {
    const missingIds = new Set<string>();
    if (this.point?.responsable && !this.users.some(u => u.id === this.point!.responsable)) {
      missingIds.add(this.point.responsable);
    }
    for (const id of this.selectedResponsables) {
      if (!this.users.some(u => u.id === id)) missingIds.add(id);
    }
    missingIds.forEach(id => {
      this.userService.getById(id).subscribe(u => { this.users = [...this.users, u]; });
    });
  }

  // Équipes proposées : celles de l'institution du point (ou de sa déléguée) ; une équipe déjà
  // affectée reste visible.
  get teamsMonInstitution(): Team[] {
    const institutionIds = this.pointInstitutionIds;
    if (institutionIds.length === 0) return this.teams;
    return this.teams.filter(t =>
      (!!t.institution && institutionIds.includes(t.institution)) ||
      t.id === this.point?.equipe ||
      this.selectedEquipesGestion.includes(t.id!) ||
      this.selectedEquipesRavitaillement.includes(t.id!)
    );
  }

  get availableCompetences(): Competence[] {
    const selectedIds = new Set(this.selectedCompetences.map(c => c.id));
    return this.allCompetences.filter(c => !selectedIds.has(c.id));
  }

  addSelectedCompetence(): void {
    if (!this.competenceSelectValue) return;
    if (this.competenceSelectValue === '__autre__') {
      const nom = this.competenceAutreLibelle.trim();
      if (!nom) return;
      this.competenceService.create({ nom }).subscribe(created => {
        this.allCompetences = [...this.allCompetences, created];
        this.onCompetenceSelected(created);
        this.competenceSelectValue = '';
        this.competenceAutreLibelle = '';
      });
      return;
    }
    const comp = this.allCompetences.find(c => c.id === this.competenceSelectValue);
    if (comp) {
      this.onCompetenceSelected(comp);
      this.competenceSelectValue = '';
    }
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['point']) {
      this.buildForm();
    }
  }

  /** Deux façons d'exister pour un centre, et il faut choisir explicitement laquelle.
   *
   * La crise était auparavant OBLIGATOIRE à la création hors contexte de crise — exactement à
   * l'envers : quand on est DANS une crise, son identifiant est déjà fourni ; quand on n'y est
   * pas, on se voyait imposer d'en choisir une. Impossible, donc, de préparer une salle des
   * fêtes à froid, alors que c'est précisément le travail de préparation d'un plan de
   * sauvegarde, que le modèle autorise (`PointOperationnel.crise` est nullable) et que la page
   * Centres sait déjà lister (onglet « Centres prévus »). */
  rattachement: 'crise' | 'avance' = 'crise';

  choisirRattachement(valeur: 'crise' | 'avance'): void {
    this.rattachement = valeur;
    const champ = this.form.get('crise');
    if (!champ) { return; }
    if (valeur === 'avance') {
      champ.setValue(null);
      champ.clearValidators();
    } else {
      champ.setValidators([Validators.required]);
    }
    champ.updateValueAndValidity();
  }

  private buildForm(): void {
    // Hors contexte de crise, le rattachement est un CHOIX : pour une crise en cours, ou à
    // l'avance pour réutilisation. Par défaut « pour une crise », qui est le cas courant ; le
    // basculement vers « à l'avance » passe par choisirRattachement, qui retire la contrainte.
    const horsCrise = !this.isEdit && !this.crisisId;
    if (horsCrise) {
      this.rattachement = 'crise';
    }
    const criseRequired = horsCrise;
    this.form = this.fb.group({
      institution: [null],
      crise: [this.point?.crise ?? this.crisisId ?? null, criseRequired ? [Validators.required] : []],
      type: [this.point?.type ?? null, Validators.required],
      nom: [this.point?.nom ?? '', Validators.required],
      description: [this.point?.description ?? ''],
      capacite_accueil: [this.point?.capacite_accueil ?? null],
      accepte_animaux: [this.point?.accepte_animaux ?? false],
      date_ouverture: [this.toDatetimeLocal(this.point?.date_ouverture)],
      date_fermeture: [this.toDatetimeLocal(this.point?.date_fermeture)],
      equipe: [this.point?.equipe ?? this.defaultEquipeId ?? null],
      responsable: [this.point?.responsable ?? null],
      // Création seulement : crée une équipe en même temps que le point.
      creerNouvelleEquipe: [false],
      nouvelleEquipeNom: [''],
    });
    this.latitude = this.point?.latitude ?? null;
    this.longitude = this.point?.longitude ?? null;

    const ids = this.point?.competences_requises ?? [];
    const libelles = this.point?.competences_requises_libelles ?? [];
    this.selectedCompetences = ids.map((id, i) => ({ id, nom: libelles[i] ?? id }));

    this.selectedEquipesGestion = this.point?.equipes_gestion_ids ?? [];
    this.selectedEquipesRavitaillement = this.point?.equipes_ravitaillement_ids ?? [];
    this.selectedResponsables = this.point?.responsables_ids ?? [];

    // Candidats recalculés à chaque changement d'équipe ou d'institution.
    this.form.get('equipe')?.valueChanges.subscribe(() => this.refreshCandidateUsers());
    this.form.get('institution')?.valueChanges.subscribe(() => this.refreshCandidateUsers());
    this.refreshCandidateUsers();
  }

  toggleEquipeGestion(id: string): void {
    if (!this.point) return;
    const ids = this.selectedEquipesGestion.includes(id)
      ? this.selectedEquipesGestion.filter(i => i !== id)
      : [...this.selectedEquipesGestion, id];
    this.pointService.update(this.point.id, { equipes_gestion_ids: ids }).subscribe(updated => {
      this.selectedEquipesGestion = ids;
      this.pointUpdated.emit(updated);
    });
  }

  toggleEquipeRavitaillement(id: string): void {
    if (!this.point) return;
    const ids = this.selectedEquipesRavitaillement.includes(id)
      ? this.selectedEquipesRavitaillement.filter(i => i !== id)
      : [...this.selectedEquipesRavitaillement, id];
    this.pointService.update(this.point.id, { equipes_ravitaillement_ids: ids }).subscribe(updated => {
      this.selectedEquipesRavitaillement = ids;
      this.pointUpdated.emit(updated);
    });
  }

  toggleResponsable(id: string): void {
    if (!this.point) return;
    const ids = this.selectedResponsables.includes(id)
      ? this.selectedResponsables.filter(i => i !== id)
      : [...this.selectedResponsables, id];
    this.pointService.update(this.point.id, { responsables_ids: ids }).subscribe(updated => {
      this.selectedResponsables = ids;
      this.pointUpdated.emit(updated);
    });
  }

  userNom(user: User): string {
    return `${user.first_name ?? ''} ${user.last_name ?? ''}`.trim() || user.email;
  }

  // Filtre client de la liste des responsables.
  responsableFilter = '';

  get filteredUsers(): User[] {
    const q = this.responsableFilter.trim().toLowerCase();
    if (!q) return this.users;
    return this.users.filter(u => this.userNom(u).toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
  }

  openVueOperationnelleModal(): void {
    this.vueOperationnelleModalOpen = true;
  }

  closeVueOperationnelleModal(): void {
    this.vueOperationnelleModalOpen = false;
  }

  onCompetenceSelected(item: Competence): void {
    if (!this.point || this.selectedCompetences.some(c => c.id === item.id)) return;
    const ids = [...this.selectedCompetences.map(c => c.id), item.id];
    this.pointService.update(this.point.id, { competences_requises: ids }).subscribe(updated => {
      this.selectedCompetences = [...this.selectedCompetences, { id: item.id, nom: item.nom }];
      this.pointUpdated.emit(updated);
    });
  }

  removeCompetence(id: string): void {
    if (!this.point) return;
    const ids = this.selectedCompetences.filter(c => c.id !== id).map(c => c.id);
    this.pointService.update(this.point.id, { competences_requises: ids }).subscribe(updated => {
      this.selectedCompetences = this.selectedCompetences.filter(c => c.id !== id);
      this.pointUpdated.emit(updated);
    });
  }

  get isEdit(): boolean {
    return !!this.point;
  }

  onCreerNouvelleEquipeChange(checked: boolean): void {
    this.form.patchValue({ creerNouvelleEquipe: checked });
    const nomControl = this.form.get('nouvelleEquipeNom');
    const equipeControl = this.form.get('equipe');
    if (checked) {
      nomControl?.setValidators([Validators.required, Validators.minLength(2)]);
      equipeControl?.setValue(null);
      equipeControl?.disable();
    } else {
      nomControl?.clearValidators();
      nomControl?.setValue('');
      equipeControl?.enable();
    }
    nomControl?.updateValueAndValidity();
  }

  openEquipeModal(): void {
    this.equipeModalOpen = true;
  }

  closeEquipeModal(): void {
    this.equipeModalOpen = false;
  }

  openInventaireModal(): void {
    this.inventaireModalOpen = true;
  }

  closeInventaireModal(): void {
    this.inventaireModalOpen = false;
  }

  /** Ouvre Signalements en mode sélection (?pickForPoint=) pour ajouter du matériel au stock. */
  ouvrirTableauOffres(): void {
    if (!this.point?.id) return;
    this.router.navigate(['/admin/signalements'], { queryParams: { pickForPoint: this.point.id } });
  }

  /** Page dédiée : le tableau (une colonne par centre) est trop large pour une modale. */
  openComparaisonModal(): void {
    if (!this.crisisId) return;
    this.router.navigate(['/admin/crises', this.crisisId, 'stocks']);
  }

  openSecretariatModal(): void {
    this.secretariatModalOpen = true;
  }

  closeSecretariatModal(): void {
    this.secretariatModalOpen = false;
  }

  onAddressSelected(addr: AddressResult | null): void {
    if (!addr) return;
    this.latitude = addr.latitude;
    this.longitude = addr.longitude;
  }

  onPositionChange(pos: { latitude: number; longitude: number }): void {
    this.latitude = pos.latitude;
    this.longitude = pos.longitude;
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }

    const { institution, crise, type, nom, description, capacite_accueil, accepte_animaux, date_ouverture, date_fermeture, equipe, responsable, creerNouvelleEquipe, nouvelleEquipeNom } = this.form.getRawValue();
    const payload: any = {
      type, nom,
      description: description || undefined,
      capacite_accueil: capacite_accueil || null,
      accepte_animaux: !!accepte_animaux,
      date_ouverture: date_ouverture || null,
      date_fermeture: date_fermeture || null,
      equipe: creerNouvelleEquipe ? null : (equipe || null),
      responsable: responsable || null,
    };
    if (creerNouvelleEquipe && nouvelleEquipeNom?.trim()) {
      payload.nouvelle_equipe_nom = nouvelleEquipeNom.trim();
    }

    if (this.latitude != null && this.longitude != null) {
      payload.location = JSON.stringify({ type: 'Point', coordinates: [this.longitude, this.latitude] });
    }

    this.saving = true;
    this.errorMessage = '';

    const request$ = this.isEdit
      ? this.pointService.update(this.point!.id, payload)
      : this.pointService.create({
          ...payload,
          crise: this.crisisId || crise || undefined,
          institution: institution || undefined,
        });

    request$.subscribe({
      next: (result) => {
        this.saving = false;
        this.saved.emit(result);
      },
      error: (err) => {
        this.saving = false;
        this.errorMessage = err.error?.crise?.[0] || err.error?.detail || "Impossible d'enregistrer ce point.";
      },
    });
  }

  close(): void {
    this.closed.emit();
  }

  private toDatetimeLocal(iso?: string | null): string {
    if (!iso) return '';
    // <input type="datetime-local"> attend "YYYY-MM-DDTHH:mm", sans le suffixe timezone ISO.
    return iso.slice(0, 16);
  }
}
