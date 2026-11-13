import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, debounceTime, distinctUntilChanged } from 'rxjs';

import { RattachementService } from '../../services/rattachement.service';
import { ContactInstitution } from '../../shared/models/institution.model';

/** Combien de lignes par page. 25 : ce qu'un écran montre sans faire défiler à l'infini, et ce
 * qui garde la requête rapide quelle que soit la taille de la base. */
const TAILLE_PAGE = 25;

/**
 * Qui est membre de quelle institution.
 *
 * Demande de Sylvain du 13/11/2026 : *« existe-t-il une page pour dire : tel utilisateur est
 * membre de telle institution ? »* — il n'y en avait pas. On pouvait voir les membres d'UNE
 * institution (fiche institution, onglet Contacts) mais jamais partir d'une personne, ni
 * chercher dans les deux sens.
 *
 * **Deux avertissements de Sylvain, et ils structurent cette page.**
 *
 * 1. *« Le même utilisateur peut être membre de plusieurs institutions. Une mairie et une
 *    asso. »* L'appartenance est donc une LISTE, pas un champ : la page groupe par personne
 *    et montre toutes ses institutions ensemble. Chercher quelqu'un et n'en voir qu'une
 *    donnerait une réponse fausse à la question posée.
 * 2. *« Fais gaffe, car à terme je pourrais avoir des milliers d'institutions. »* Rien n'est
 *    chargé globalement : la recherche et la pagination sont **côté serveur**, et la page ne
 *    tient jamais en mémoire plus que ce qu'elle affiche. C'est l'inverse de ce que faisait
 *    `/admin/institutions`, qui tirait toutes les institutions, tous les comptes et tous les
 *    rattachements à l'ouverture.
 */
@Component({
  selector: 'app-rattachements',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './rattachements.component.html',
  styleUrl: './rattachements.component.scss',
})
export class RattachementsComponent implements OnInit {
  chargement = true;
  erreur = '';
  message = '';

  recherche = '';
  page = 1;
  total = 0;
  rattachements: ContactInstitution[] = [];
  /** Inclure les rattachements désactivés. Faux par défaut : on cherche qui est membre, pas
   * qui l'a été. */
  inclureInactifs = false;

  private frappe$ = new Subject<string>();

  constructor(private service: RattachementService) {}

  ngOnInit(): void {
    // 350 ms : assez pour qu'une frappe normale ne déclenche qu'une requête, assez court pour
    // que le résultat paraisse immédiat. Sans cela, chercher « saint-étienne » lancerait
    // treize requêtes serveur.
    this.frappe$.pipe(debounceTime(350), distinctUntilChanged()).subscribe(() => {
      this.page = 1;
      this.charger();
    });
    this.charger();
  }

  onRecherche(valeur: string): void {
    this.recherche = valeur;
    this.frappe$.next(valeur);
  }

  charger(): void {
    this.chargement = true;
    this.erreur = '';
    this.service.rechercher({
      recherche: this.recherche,
      page: this.page,
      pageSize: TAILLE_PAGE,
      actif: this.inclureInactifs ? undefined : true,
    }).subscribe({
      next: (reponse) => {
        this.rattachements = reponse.results;
        this.total = reponse.count;
        this.chargement = false;
      },
      error: () => {
        this.erreur = 'Impossible de charger les rattachements.';
        this.chargement = false;
      },
    });
  }

  basculerInactifs(): void {
    this.inclureInactifs = !this.inclureInactifs;
    this.page = 1;
    this.charger();
  }

  /** Les rattachements de la page, groupés par personne.
   *
   * Le groupement se fait sur CE QUE LE SERVEUR A RENVOYÉ, donc sur une page : quelqu'un dont
   * les deux institutions tombent de part et d'autre d'une coupure apparaîtra dans les deux
   * pages. C'est assumé — l'alternative serait de paginer par personne, ce qui obligerait le
   * serveur à agréger avant de compter, pour un cas que la recherche résout mieux : on tape le
   * nom, et on voit tout.
   */
  get parPersonne(): { nom: string; email: string; lignes: ContactInstitution[] }[] {
    const groupes = new Map<string, { nom: string; email: string; lignes: ContactInstitution[] }>();
    for (const ligne of this.rattachements) {
      const cle = ligne.utilisateur;
      if (!groupes.has(cle)) {
        groupes.set(cle, {
          nom: ligne.utilisateur_nom || ligne.utilisateur_email || 'Compte sans nom',
          email: ligne.utilisateur_email || '',
          lignes: [],
        });
      }
      groupes.get(cle)!.lignes.push(ligne);
    }
    return [...groupes.values()]
      .sort((a, b) => a.nom.localeCompare(b.nom, 'fr'));
  }

  get nombreDePages(): number {
    return Math.max(1, Math.ceil(this.total / TAILLE_PAGE));
  }

  pagePrecedente(): void {
    if (this.page > 1) { this.page--; this.charger(); }
  }

  pageSuivante(): void {
    if (this.page < this.nombreDePages) { this.page++; this.charger(); }
  }

  /** Désactiver plutôt que supprimer : un rattachement retiré fait perdre l'ancienneté et
   * l'historique. `actif=false` retire les droits sans effacer le passé. */
  retirerLesDroits(ligne: ContactInstitution): void {
    if (!ligne.id) { return; }
    this.service.basculerActif(ligne.id, false).subscribe({
      next: (maj) => {
        this.rattachements = this.rattachements.map(l => (l.id === maj.id ? maj : l));
        this.message = 'Rattachement désactivé : les droits sont retirés, l\'historique reste.';
        if (!this.inclureInactifs) { this.charger(); }
      },
      error: (err) => this.erreur = err?.error?.error
        || 'Impossible de modifier ce rattachement.',
    });
  }

  reactiver(ligne: ContactInstitution): void {
    if (!ligne.id) { return; }
    this.service.basculerActif(ligne.id, true).subscribe({
      next: (maj) => {
        this.rattachements = this.rattachements.map(l => (l.id === maj.id ? maj : l));
        this.message = 'Rattachement réactivé.';
      },
      error: (err) => this.erreur = err?.error?.error
        || 'Impossible de modifier ce rattachement.',
    });
  }
}
