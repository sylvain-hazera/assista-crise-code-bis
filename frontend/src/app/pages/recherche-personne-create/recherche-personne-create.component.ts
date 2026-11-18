import { RETOUR_STANDARD, SaisieStandard, lireSaisieStandard, marquerSaisieStandard, nouvelleSaisiePourAutrui } from '../../shared/utils/saisie-standard';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Component } from '@angular/core';
import { CrisisService } from '../../services/crisis.service';
import { RecherchePersonneService } from '../../services/recherche-personne.service';
import { AuthService } from '../../auth/services/auth.service';
import { Router, RouterLink } from '@angular/router';

@Component({
  selector: 'app-recherche-personne-create',
  standalone: true,
  imports: [
    CommonModule,
    RouterLink,
    FormsModule
  ],
  templateUrl: './recherche-personne-create.component.html',
  styleUrls: ['./recherche-personne-create.component.scss']
})
export class RecherchePersonneCreateComponent {

  crises: any[] = [];

  modele: any = {
    source: 'EHPAD'
  };

  fichier?: File;
  previewUrl: string | null = null;

  constructor(
    private service: RecherchePersonneService,
    private crisisService: CrisisService,
    private authService: AuthService,
    private router: Router
  ) {}

  onFileSelected(event: any): void {

    if (
      event.target.files &&
      event.target.files.length > 0
    ) {

      const file = event.target.files[0];

      this.fichier = file;

      this.previewUrl =
        URL.createObjectURL(file);

    }

  }

  /** Non nul quand le standard de crise remplit ce formulaire pour quelqu'un qui téléphone. */
  saisieStandard: SaisieStandard | null = null;

  get peutSaisirPourAutrui(): boolean { return !!this.authService.isInstitutionalEffective?.(); }

  /** Coche ou décoche « enregistré par la collectivité à la demande de la personne ». */
  definirPourAutrui(coche: boolean): void {
    this.saisieStandard = coche ? nouvelleSaisiePourAutrui() : null;
    const moi = this.authService.getCurrentUser();
    this.modele.contact_nom = coche ? '' : `${moi?.first_name ?? ''} ${moi?.last_name ?? ''}`.trim();
    this.modele.contact_email = coche ? '' : (moi?.email ?? '');
    this.modele.contact_telephone = coche ? '' : (moi?.phone_number || '');
  }

  ngOnInit(): void {

    this.crisisService
      .getAll()
      .subscribe(data => {

        this.crises = data;

      });

    this.saisieStandard = lireSaisieStandard(this.authService);

    const currentUser =
      this.authService.getCurrentUser();

    // Au standard, le contact est l'appelant : rien n'est repris du compte de l'agent.
    if (currentUser && !this.saisieStandard) {

      this.modele.contact_nom =
        `${currentUser.first_name ?? ''} ${currentUser.last_name ?? ''}`.trim();

      this.modele.contact_email =
        currentUser.email ?? '';

      this.modele.contact_telephone =
        currentUser.phone_number || '';
    }
  }

  enregistrer(): void {

    if (!this.modele.crise) {

      alert(
        'Veuillez sélectionner une crise'
      );

      return;

    }

    const formData = new FormData();

    Object.keys(this.modele).forEach(key => {

      if (
        this.modele[key] !== null &&
        this.modele[key] !== undefined
      ) {

        formData.append(
          key,
          this.modele[key]
        );

      }

    });

    if (this.fichier) {

      formData.append(
        'photo',
        this.fichier
      );

    }

    marquerSaisieStandard(formData, this.saisieStandard);

    this.service
      .create(formData)
      .subscribe(() => {
        if (this.saisieStandard) { this.router.navigate([RETOUR_STANDARD]); return; }

        // Le dépôt est ouvert à tout compte authentifié (voir public.routes.ts), mais la liste
        // /recherches-personnes reste réservée aux acteurs institutionnels (institutional
        // EffectiveGuard) -- y rediriger un simple citoyen qui vient de déposer sa fiche le
        // renvoyait tout droit sur /admin/acces-refuse, juste après un dépôt réussi. Seul un
        // acteur institutionnel est renvoyé vers le registre ; les autres vers l'accueil.
        this.router.navigate([
          this.authService.isInstitutionalEffective() ? '/recherches-personnes' : '/accueil'
        ]);

      });

  }

}
