import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { DemandeMobilisationService } from '../../services/demande-mobilisation.service';
import { CrisisService } from '../../services/crisis.service';
import { UserService } from '../../services/user.service';
import { InstitutionService } from '../../services/institution.service';
import { OfferService } from '../../services/offer.service';
import { AuthService } from '../../auth/services/auth.service';
import { DemandeMobilisation, TypeDemandeMobilisation } from '../../shared/models/demande-mobilisation.model';
import { Crisis } from '../../shared/models/crisis.model';
import { User } from '../../shared/models/user.model';
import { Institution } from '../../shared/models/institution.model';
import { Offer } from '../../shared/models/offer.model';

type TypeCible = 'utilisateur' | 'institution' | 'offre';

/** Acter qu'une institution ("l'autorité X") demande à quelqu'un ("Y" — un utilisateur inscrit,
 * une autre institution, ou une personne sans compte connue via une offre d'aide déposée) de se
 * mettre à disposition ou de se rendre à un endroit précis, pour une crise donnée — voir
 * DemandeMobilisation.__doc__ côté backend pour la nuance volontaire avec une "réquisition"
 * légale au sens strict. Base pour une future attestation PDF + QR code (pas construite à ce
 * stade, voir le cadrage du 2026-09-19) — jeton_verification est déjà posé en prévision. */
@Component({
  selector: 'app-demandes-mobilisation',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './demandes-mobilisation.component.html',
  styleUrl: './demandes-mobilisation.component.scss',
})
export class DemandesMobilisationComponent implements OnInit {
  demandes: DemandeMobilisation[] = [];
  loading = true;
  errorMessage = '';

  crises: Crisis[] = [];
  utilisateurs: User[] = [];
  institutions: Institution[] = [];
  offres: Offer[] = [];

  institutionEmettriceId: string | null = null;
  institutionEmettriceNom: string | null = null;

  // ── Formulaire de création ──────────────────────────────────────────────
  formOuvert = false;
  criseId = '';
  typeCible: TypeCible = 'utilisateur';
  cibleId = '';
  rechercheCible = '';
  typeDemande: TypeDemandeMobilisation = 'MISE_A_DISPOSITION';
  lieuTexte = '';
  motif = '';
  soumission = false;
  formErreur = '';

  constructor(
    private service: DemandeMobilisationService,
    private crisisService: CrisisService,
    private userService: UserService,
    private institutionService: InstitutionService,
    private offerService: OfferService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    const user = this.authService.getCurrentUser();
    this.institutionEmettriceId = user?.institution_id ?? null;
    this.institutionEmettriceNom = user?.institution_nom ?? null;

    this.load();
    this.crisisService.getAll().subscribe(list => this.crises = list.filter(c => !c.end_date));
    this.userService.getAll().subscribe(list => this.utilisateurs = list);
    this.institutionService.getAll().subscribe(list => this.institutions = list);
    this.offerService.getAll().subscribe(list => this.offres = list);
  }

  load(): void {
    this.loading = true;
    this.errorMessage = '';
    this.service.getAll().subscribe({
      next: (list) => { this.demandes = list; this.loading = false; },
      error: () => { this.errorMessage = 'Impossible de charger les demandes de mobilisation.'; this.loading = false; },
    });
  }

  get utilisateursFiltres(): User[] {
    const q = this.rechercheCible.trim().toLowerCase();
    if (!q) return this.utilisateurs.slice(0, 50);
    return this.utilisateurs.filter(u =>
      `${u.first_name} ${u.last_name} ${u.email}`.toLowerCase().includes(q)
    ).slice(0, 50);
  }

  get institutionsFiltrees(): Institution[] {
    const q = this.rechercheCible.trim().toLowerCase();
    if (!q) return this.institutions.slice(0, 50);
    return this.institutions.filter(i => i.nom.toLowerCase().includes(q)).slice(0, 50);
  }

  get offresFiltrees(): Offer[] {
    const q = this.rechercheCible.trim().toLowerCase();
    if (!q) return this.offres.slice(0, 50);
    return this.offres.filter(o =>
      `${o.first_name_offer} ${o.last_name_offer} ${o.title}`.toLowerCase().includes(q)
    ).slice(0, 50);
  }

  changerTypeCible(type: TypeCible): void {
    this.typeCible = type;
    this.cibleId = '';
    this.rechercheCible = '';
  }

  get formValide(): boolean {
    return !!this.institutionEmettriceId && !!this.criseId && !!this.cibleId && !!this.typeDemande
      && (this.typeDemande !== 'SE_RENDRE_A' || !!this.lieuTexte.trim());
  }

  ouvrirFormulaire(): void {
    this.formOuvert = true;
    this.formErreur = '';
  }

  annulerFormulaire(): void {
    this.formOuvert = false;
    this.criseId = '';
    this.cibleId = '';
    this.rechercheCible = '';
    this.typeDemande = 'MISE_A_DISPOSITION';
    this.lieuTexte = '';
    this.motif = '';
    this.formErreur = '';
  }

  envoyer(): void {
    if (!this.formValide || !this.institutionEmettriceId) return;
    this.soumission = true;
    this.formErreur = '';

    const payload = {
      crise: this.criseId,
      institution_emettrice: this.institutionEmettriceId,
      type_demande: this.typeDemande,
      lieu_texte: this.typeDemande === 'SE_RENDRE_A' ? this.lieuTexte.trim() : '',
      motif: this.motif.trim(),
      cible_utilisateur: this.typeCible === 'utilisateur' ? this.cibleId : null,
      cible_institution: this.typeCible === 'institution' ? this.cibleId : null,
      cible_offre: this.typeCible === 'offre' ? this.cibleId : null,
    };

    this.service.create(payload).subscribe({
      next: (creee) => {
        this.demandes = [creee, ...this.demandes];
        this.soumission = false;
        this.annulerFormulaire();
      },
      error: (err) => {
        this.soumission = false;
        this.formErreur = err.error?.error || err.error?.cible?.[0] || "Impossible d'envoyer cette demande.";
      },
    });
  }

  revoquerEnCours: string | null = null;
  revoquerErreur = '';

  revoquer(demande: DemandeMobilisation): void {
    if (!confirm(`Révoquer cette demande à « ${demande.cible_nom} » ?`)) return;
    this.revoquerEnCours = demande.id;
    this.revoquerErreur = '';
    this.service.revoquer(demande.id).subscribe({
      next: (mise_a_jour) => {
        const idx = this.demandes.findIndex(d => d.id === mise_a_jour.id);
        if (idx !== -1) this.demandes[idx] = mise_a_jour;
        this.revoquerEnCours = null;
      },
      error: (err) => {
        this.revoquerErreur = err.error?.error || 'Impossible de révoquer cette demande.';
        this.revoquerEnCours = null;
      },
    });
  }

  statutClass(demande: DemandeMobilisation): string {
    return demande.statut === 'ACTIVE' ? 'statut-active' : 'statut-revoquee';
  }
}
