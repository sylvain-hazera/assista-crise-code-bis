import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { UserService } from '../../../services/user.service';
import { RoleOperationnelService } from '../../../services/role-operationnel.service';
import { InstitutionTypeService } from '../../../services/institution-type.service';
import { RoleOperationnel, InstitutionType } from '../../../shared/models/institution.model';
import { AuthService } from '../../services/auth.service';

type Etape = 'chargement' | 'confirmation' | 'creation' | 'erreur';

// Codes de type d'institution pour lesquels la convention de sous-traitance RGPD (article 28)
// est exigée à l'activation — voir CODES_TYPES_COLLECTIVITE (backend/core/
// convention_sous_traitance.py), à garder synchronisé.
const CODES_TYPES_COLLECTIVITE = ['mairie', 'epci', 'sdis'];

/**
 * Écran affiché juste après l'activation d'un compte "Autorité locale" (mairie, préfecture,
 * EPCI, hôpital...) tant qu'il n'est rattaché à aucune institution — soit l'institution a été
 * retrouvée automatiquement (domaine connu ou annuaire officiel) et il ne reste qu'à confirmer
 * avec son rôle, soit rien n'a été trouvé et il crée lui-même son institution (mêmes champs que
 * le formulaire admin, voir InstitutionViewSet). Reste accessible tant que
 * `needs_institution_setup` est vrai (voir header.component pour le rappel persistant) : la
 * personne peut fermer l'onglet avant d'avoir fini sans rien perdre.
 */
@Component({
  selector: 'app-completer-inscription',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './completer-inscription.component.html',
  styleUrl: './completer-inscription.component.scss',
})
export class CompleterInscriptionComponent implements OnInit {
  etape: Etape = 'chargement';
  errorMessage = '';
  submitting = false;

  institutionTrouvee: { id: string; nom: string; type_libelle?: string | null } | null = null;
  roles: RoleOperationnel[] = [];
  institutionTypes: InstitutionType[] = [];

  // Convention de sous-traitance RGPD (article 28) : côté "confirmation", connu directement par
  // institutionSuggestion (l'institution est déjà déterminée) ; côté "création", recalculé à
  // chaque changement de type sélectionné (voir onTypeChange).
  conventionRequisePourConfirmation = false;
  conventionRequisePourCreation = false;

  roleForm!: FormGroup;
  creationForm!: FormGroup;

  constructor(
    private fb: FormBuilder,
    private router: Router,
    private userService: UserService,
    private roleService: RoleOperationnelService,
    private institutionTypeService: InstitutionTypeService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.roleForm = this.fb.group({
      role_code: ['', Validators.required],
      convention_acceptee: [false],
    });
    this.creationForm = this.fb.group({
      nom: ['', [Validators.required, Validators.minLength(2)]],
      type: [null, Validators.required],
      description: [''],
      telephone: [''],
      email: ['', Validators.email],
      adresse: [''],
      commune_code: [''],
      commune_nom: [''],
      role_code: ['', Validators.required],
      convention_acceptee: [false],
    });

    this.creationForm.get('type')!.valueChanges.subscribe(() => this.onTypeChange());

    this.roleService.getAll().subscribe(roles => this.roles = roles);
    this.institutionTypeService.getAll().subscribe(types => {
      this.institutionTypes = types;
      this.onTypeChange();
    });

    this.userService.institutionSuggestion().subscribe({
      next: (res) => {
        this.institutionTrouvee = res.institution;
        this.conventionRequisePourConfirmation = res.convention_requise;
        if (res.institution) {
          this.etape = 'confirmation';
        } else {
          this.creationForm.patchValue({
            nom: res.pending_institution_name || '',
            commune_nom: res.pending_commune_name || '',
            commune_code: res.pending_commune_code || '',
          });
          this.etape = 'creation';
        }
      },
      error: () => {
        // Rien en attente (compte déjà rattaché, ou pas de ce type) : rien à faire ici.
        this.router.navigate(['/accueil']);
      },
    });
  }

  /** Recalcule si le type sélectionné dans creationForm exige la convention de sous-traitance
   * RGPD (mairie/EPCI/SDIS) — appelé au changement de type et une fois les types chargés. */
  private onTypeChange(): void {
    const typeId = this.creationForm?.get('type')?.value;
    const type = this.institutionTypes.find(t => t.id === typeId);
    this.conventionRequisePourCreation = !!type && CODES_TYPES_COLLECTIVITE.includes(type.code.toLowerCase());
    if (!this.conventionRequisePourCreation) {
      this.creationForm.patchValue({ convention_acceptee: false }, { emitEvent: false });
    }
  }

  /** Bascule vers la création si, finalement, l'institution proposée n'est pas la bonne. */
  passerALaCreation(): void {
    this.etape = 'creation';
  }

  confirmer(): void {
    if (this.roleForm.invalid) {
      this.roleForm.markAllAsTouched();
      return;
    }
    if (this.conventionRequisePourConfirmation && !this.roleForm.value.convention_acceptee) {
      this.errorMessage = "Vous devez accepter la convention de sous-traitance pour continuer.";
      return;
    }
    this.submitting = true;
    this.errorMessage = '';
    this.userService.confirmerInstitution(
      this.roleForm.value.role_code, this.roleForm.value.convention_acceptee,
    ).subscribe({
      next: () => {
        this.authService.fetchMe().subscribe(() => this.router.navigate(['/accueil']));
      },
      error: (err) => {
        this.submitting = false;
        this.errorMessage = err.error?.error || err.error?.convention_acceptee || "Impossible de confirmer ce rattachement.";
      },
    });
  }

  creer(): void {
    if (this.creationForm.invalid) {
      this.creationForm.markAllAsTouched();
      return;
    }
    if (this.conventionRequisePourCreation && !this.creationForm.value.convention_acceptee) {
      this.errorMessage = "Vous devez accepter la convention de sous-traitance pour continuer.";
      return;
    }
    this.submitting = true;
    this.errorMessage = '';
    this.userService.creerMonInstitution(this.creationForm.value).subscribe({
      next: () => {
        this.authService.fetchMe().subscribe(() => this.router.navigate(['/accueil']));
      },
      error: (err) => {
        this.submitting = false;
        this.errorMessage = err.error?.error || err.error?.convention_acceptee || err.error?.nom?.[0] || "Impossible de créer cette institution.";
      },
    });
  }
}
