import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ArticleCatalogueDon, FamilleCatalogueDon, LABELS_PUBLIC_DON, LigneDon, PublicDon } from '../../shared/models/appel-dons.model';

/**
 * Choisir précisément un don : famille, article, pour qui, quelle taille, combien. C'est ce
 * qui fait qu'un appel dit « T-shirt homme L : 3 » et non « des vêtements ».
 */
@Component({
  selector: 'app-choix-don',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="choix-don">
      <label>Famille
        <select name="famille" [(ngModel)]="famille" (ngModelChange)="article = null; public = ''; taille = ''">
          <option value="">— Choisir —</option>
          @for (f of catalogue; track f.famille) { <option [value]="f.famille">{{ f.libelle }}</option> }
        </select></label>
      @if (famille) {
        <label>Article
          <select name="article" [(ngModel)]="article" (ngModelChange)="surArticle()">
            <option [ngValue]="null">— Choisir —</option>
            @for (a of articles; track a.designation) { <option [ngValue]="a">{{ a.designation }}</option> }
            <option [ngValue]="AUTRE">Autre (à décrire)</option>
          </select></label>
      }
      @if (article === AUTRE) { <label>Quoi <input type="text" name="libre" maxlength="120" [(ngModel)]="libre" placeholder="Fauteuil roulant"></label> }
      @if (article && article !== AUTRE && article.publics.length) {
        <label>Pour
          <select name="public" [(ngModel)]="public" (ngModelChange)="taille = ''">
            @for (p of article.publics; track p) { <option [value]="p">{{ publics[p] }}</option> }
          </select></label>
      }
      @if (tailles.length) {
        <label>Taille
          <select name="taille" [(ngModel)]="taille">
            <option value="">— Choisir —</option>
            @for (t of tailles; track t) { <option [value]="t">{{ t }}</option> }
          </select></label>
      }
      <label>Quantité <input type="number" name="quantite" min="1" step="1" [(ngModel)]="quantite"></label>
      <label class="mot">Un mot personnel (facultatif)
        <input type="text" name="message" maxlength="300" [(ngModel)]="message" placeholder="Elle avait un vélo rose, avec un panier"></label>
      <button type="button" class="btn-secondary" [disabled]="!complet" (click)="ajouter()">Ajouter</button>
    </div>`,
  styles: [`.choix-don { display: flex; flex-wrap: wrap; gap: .6rem; align-items: end; }
    label { display: grid; gap: .2rem; font-weight: 600; font-size: .88rem; }
    input, select { font: inherit; font-weight: 400; padding: .4rem .5rem; } input[type=number] { width: 6rem; } label.mot { flex: 1 1 16rem; }`],
})
export class ChoixDonComponent {
  @Input() catalogue: FamilleCatalogueDon[] = [];
  @Output() choisi = new EventEmitter<LigneDon>();

  readonly publics = LABELS_PUBLIC_DON;
  readonly AUTRE: ArticleCatalogueDon = { designation: '', publics: [], mesure: '', neuf_exige: false, quantite: 1, quantite_urgence: 1, tailles: {} };

  famille = '';
  article: ArticleCatalogueDon | null = null;
  public: PublicDon | '' = '';
  taille = '';
  libre = '';
  quantite = 1;
  /** Lu de tous, avis public compris : on y décrit l'objet, jamais la personne par son nom. */
  message = '';

  get articles(): ArticleCatalogueDon[] { return this.catalogue.find(f => f.famille === this.famille)?.articles ?? []; }
  get tailles(): string[] { return this.article && this.article !== this.AUTRE ? (this.article.tailles[this.public] ?? []) : []; }

  surArticle(): void {
    this.public = this.article?.publics[0] ?? '';
    this.taille = '';
    this.quantite = this.article && this.article !== this.AUTRE ? this.article.quantite : 1;
  }

  get complet(): boolean {
    if (!this.famille || !this.article || !(this.quantite >= 1)) return false;
    if (this.article === this.AUTRE) return !!this.libre.trim();
    return !this.tailles.length || !!this.taille;         // une taille quand l'article en a
  }

  ajouter(): void {
    if (!this.complet || !this.article) return;
    this.choisi.emit({ famille: this.famille, designation: this.article === this.AUTRE ? this.libre.trim() : this.article.designation,
      public: this.article === this.AUTRE ? '' : this.public, taille: this.taille, neuf_exige: this.article.neuf_exige, quantite: Math.floor(this.quantite),
      quantite_urgence: Math.max(1, Math.floor(this.quantite / 2)), message: this.message.trim() });
    this.taille = '';
    this.libre = '';
    this.message = '';
  }
}
