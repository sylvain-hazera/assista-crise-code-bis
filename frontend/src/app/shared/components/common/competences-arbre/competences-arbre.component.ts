import { Component, EventEmitter, Input, OnInit, Output, inject } from '@angular/core';
import { CompetenceService } from '../../../../services/competence.service';
import { Competence } from '../../../models/competence.model';
import { TagSearchInputComponent } from '../tag-search-input/tag-search-input.component';

interface Groupe { parent: Competence; children: Competence[]; }

/**
 * L'arbre des compétences (thèmes et sous-thèmes du catalogue `Competence`), choix multiple.
 *
 * Un seul composant pour « Proposer mon aide » et la fiche de bénévole (21/11/2026) : un membre
 * de l'association et un bénévole spontané décrivent ce qu'ils savent faire dans le MÊME
 * vocabulaire, sans quoi une campagne ou un point qui demande « Pompage » ne trouverait que les
 * uns ou les autres. Menu fermé par défaut, sous-thèmes repliés tant qu'on ne déplie pas leur
 * parent ; « Autre (préciser)… » cherche ou propose une compétence absente.
 *
 * Seules les compétences actives sont proposées : désactiver une compétence la retire des listes.
 */
@Component({
  selector: 'app-competences-arbre',
  standalone: true,
  imports: [TagSearchInputComponent],
  templateUrl: './competences-arbre.component.html',
  styleUrl: './competences-arbre.component.scss',
})
export class CompetencesArbreComponent implements OnInit {
  private service = inject(CompetenceService);

  @Input() selection: Competence[] = [];
  @Output() selectionChange = new EventEmitter<Competence[]>();

  catalogue: Competence[] = [];
  ouvert = false;
  autre = false;
  private deplies = new Set<string>();
  readonly chercher = (q: string) => this.service.search(q);
  readonly creer = (nom: string) => this.service.create({ nom });

  ngOnInit(): void {
    this.service.getAll().subscribe({
      next: (liste) => this.catalogue = liste.filter(c => c.active !== false),
      error: () => {},
    });
  }

  get groupes(): Groupe[] {
    return this.catalogue.filter(c => !c.parent).map(parent => ({
      parent, children: this.catalogue.filter(c => c.parent === parent.id),
    }));
  }

  estDeplie(id: string): boolean { return this.deplies.has(id); }
  basculerDeplie(id: string): void {
    if (this.deplies.has(id)) this.deplies.delete(id); else this.deplies.add(id);
  }

  estCoche(id: string): boolean { return this.selection.some(c => c.id === id); }

  ajouter(c: Competence): void {
    if (this.estCoche(c.id)) return;
    this.emettre([...this.selection, c]);
  }

  retirer(id: string): void { this.emettre(this.selection.filter(c => c.id !== id)); }

  basculer(c: Competence): void { if (this.estCoche(c.id)) this.retirer(c.id); else this.ajouter(c); }

  etat(g: Groupe): 'all' | 'some' | 'none' {
    const ids = [g.parent.id, ...g.children.map(c => c.id)];
    const n = ids.filter(id => this.estCoche(id)).length;
    return n === 0 ? 'none' : n === ids.length ? 'all' : 'some';
  }

  /** Coche ou décoche le thème et tous ses sous-thèmes. */
  basculerGroupe(g: Groupe): void {
    const membres = [g.parent, ...g.children];
    const tout = membres.every(c => this.estCoche(c.id));
    const ids = new Set(membres.map(c => c.id));
    this.emettre(tout ? this.selection.filter(c => !ids.has(c.id))
                      : [...this.selection, ...membres.filter(c => !this.estCoche(c.id))]);
  }

  private emettre(liste: Competence[]): void {
    this.selection = liste;
    this.selectionChange.emit(liste);
  }
}
