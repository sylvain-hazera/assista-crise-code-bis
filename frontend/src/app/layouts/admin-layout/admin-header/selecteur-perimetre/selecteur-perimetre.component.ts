import { Component, DestroyRef, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged, switchMap, of, catchError } from 'rxjs';

import { AuthService } from '../../../../auth/services/auth.service';
import { EtatPerimetre, InstitutionPerimetre, PerimetreService } from '../../../../services/perimetre.service';
import { UserRole } from '../../../../shared/models/user.model';

/** « Je regarde… » : le périmètre de consultation d'un administrateur (voir PerimetreService).
 *
 * 23/11/2026 : la liste déroulante était coupée à 500 institutions (plus de 550 après
 * l'amorçage de la Gironde). On cherche désormais : quelques lettres du nom, de la commune
 * ou du code postal, et chaque résultat montre son code postal. */
@Component({
  selector: 'app-selecteur-perimetre',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './selecteur-perimetre.component.html',
  styleUrl: './selecteur-perimetre.component.scss',
})
export class SelecteurPerimetreComponent implements OnInit {
  readonly MIENNE = PerimetreService.MIENNE;
  readonly TOUT = PerimetreService.TOUT;

  etat: EtatPerimetre | null = null;
  choix = PerimetreService.MIENNE;
  ouvert = false;
  recherche = '';
  cherche = false;
  trouvees: InstitutionPerimetre[] = [];

  @ViewChild('champ') champ?: ElementRef<HTMLInputElement>;
  private readonly frappe = new Subject<string>();
  private readonly detruit = inject(DestroyRef);

  constructor(private perimetre: PerimetreService, private auth: AuthService) {}

  get visible(): boolean {
    return this.auth.getEffectiveRole() === UserRole.ADMIN && !!this.etat?.administrateur;
  }

  ngOnInit(): void {
    if (this.auth.getEffectiveRole() !== UserRole.ADMIN) { return; }
    this.choix = this.perimetre.choix;
    this.perimetre.etat().subscribe({
      next: (etat) => {
        this.etat = etat;
        // Le choix gardé ne désigne plus rien : retour à « mon institution ».
        if (etat.mode === 'INVALIDE') { this.choisir(this.MIENNE); return; }
        // Un administrateur sans institution regarde forcément toute la plateforme.
        if (this.choix === this.MIENNE && !etat.mienne) { this.choix = this.TOUT; }
      },
      error: () => { this.etat = null; },
    });
    this.frappe.pipe(
      debounceTime(250),
      distinctUntilChanged(),
      switchMap(q => q.trim().length < 2 ? of(null) : this.perimetre.rechercher(q.trim()).pipe(catchError(() => of(null)))),
      takeUntilDestroyed(this.detruit),
    ).subscribe(etat => {
      this.trouvees = etat?.institutions ?? [];
      this.cherche = false;
    });
  }

  /** Les institutions trouvées, hors la sienne (elle a son entrée en tête). */
  get autres(): InstitutionPerimetre[] {
    const mienne = this.etat?.mienne?.id;
    return this.trouvees.filter(i => i.id !== mienne);
  }

  get libelleCourant(): string {
    if (this.choix === this.TOUT) return 'Toute la plateforme';
    if (this.choix === this.MIENNE) return this.etat?.mienne ? `Mon institution — ${this.etat.mienne.nom}` : 'Mon institution';
    const i = this.etat?.institution;
    return i ? `${i.nom}${i.code_postal ? ' (' + i.code_postal + ')' : ''}` : 'Une autre institution';
  }

  /** Vrai quand l'administrateur ne regarde pas son institution : le sélecteur le souligne. */
  get horsDeChezSoi(): boolean {
    return this.choix !== this.MIENNE;
  }

  basculer(): void {
    this.ouvert = !this.ouvert;
    if (this.ouvert) setTimeout(() => this.champ?.nativeElement.focus());
  }

  fermer(): void { this.ouvert = false; }

  taper(q: string): void {
    this.recherche = q;
    this.cherche = q.trim().length >= 2;
    this.frappe.next(q);
  }

  /** Entrée dans le champ : le premier résultat. */
  premier(): void {
    const i = this.autres[0];
    if (i) this.choisir(i.id);
  }

  choisir(choix: string): void {
    this.ouvert = false;
    if (!choix || choix === this.perimetre.choix) { return; }
    this.perimetre.definir(choix);
    this.recharger();
  }

  /** À part pour que les tests puissent l'observer sans recharger la page de test. */
  recharger(): void {
    window.location.reload();
  }
}
