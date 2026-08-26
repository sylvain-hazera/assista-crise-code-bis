import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subject } from 'rxjs';
import { debounceTime, distinctUntilChanged, switchMap, catchError } from 'rxjs/operators';
import { of } from 'rxjs';

/**
 * Widget générique "chercher ou créer un thème/hashtag" : tape des mots-clés (peu importe
 * l'ordre, cf. searchFn côté backend), voit les thèmes existants qui matchent, ou crée le
 * sien s'il n'existe pas encore — réutilisable partout où l'app pioche dans un vocabulaire
 * partagé et extensible (compétences, types de signalement...). Ne gère qu'une sélection à
 * la fois : les écrans multi-sélection (ex: thèmes d'une équipe) l'utilisent comme point
 * d'ajout et gèrent eux-mêmes leur propre liste de choix déjà faits.
 */
@Component({
  selector: 'app-tag-search-input',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './tag-search-input.component.html',
  styleUrl: './tag-search-input.component.scss'
})
export class TagSearchInputComponent<T = any> {

  @Input({ required: true }) searchFn!: (query: string) => Observable<T[]>;
  @Input({ required: true }) createFn!: (value: string) => Observable<T>;
  @Input() labelField = 'nom';
  @Input() placeholder = 'Rechercher ou créer un thème...';

  @Output() itemSelected = new EventEmitter<T>();

  query = '';
  results: T[] = [];
  showDropdown = false;
  loading = false;
  creating = false;

  private search$ = new Subject<string>();

  constructor() {
    this.search$
      .pipe(
        debounceTime(250),
        distinctUntilChanged(),
        switchMap(q => {
          if (!q.trim()) {
            return of([]);
          }
          this.loading = true;
          return this.searchFn(q).pipe(catchError(() => of([])));
        })
      )
      .subscribe(results => {
        this.results = results;
        this.loading = false;
      });
  }

  onQueryChange(value: string): void {
    this.query = value;
    this.showDropdown = true;
    this.search$.next(value);
  }

  label(item: T): string {
    return (item as any)[this.labelField];
  }

  hasExactMatch(): boolean {
    const q = this.query.trim().toLowerCase();
    return this.results.some(r => this.label(r).trim().toLowerCase() === q);
  }

  select(item: T): void {
    this.itemSelected.emit(item);
    this.reset();
  }

  createNew(): void {
    const value = this.query.trim();
    if (!value || this.creating) {
      return;
    }
    this.creating = true;
    this.createFn(value).subscribe({
      next: item => {
        this.creating = false;
        this.select(item);
      },
      error: () => {
        this.creating = false;
      }
    });
  }

  onBlur(): void {
    // Laisse le temps au (click) sur une option du dropdown de se déclencher avant de le fermer.
    setTimeout(() => (this.showDropdown = false), 150);
  }

  private reset(): void {
    this.query = '';
    this.results = [];
    this.showDropdown = false;
  }
}
