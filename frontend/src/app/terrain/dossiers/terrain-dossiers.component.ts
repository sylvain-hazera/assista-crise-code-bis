import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { Dossier } from '../../shared/models/dossier.model';
import { HorsLigneService } from '../hors-ligne.service';
import { PhotosTerrainService } from '../photo/photos-terrain.service';

interface PhotoDossier { id: string; auteur_nom: string; date_upload: string | null; commentaire: string | null; sha256: string | null; }

const STATUTS_CLOS = ['RESOLU', 'CLOTURE'];

/**
 * Mes dossiers, côté terrain (DOSSIER-PWA-INTERVENANTS.md, lot 5) : les dossiers de mes équipes,
 * lisibles sans réseau, et des **photos scellées** à leur joindre — réduites, datées, situées et
 * scellées par leur empreinte au moment de la prise, puis envoyées dès que le réseau le permet.
 */
@Component({
  selector: 'app-terrain-dossiers',
  imports: [DatePipe],
  template: `
    <h1>Mes dossiers</h1>
    @if (copieDu()) {
      <p class="copie" role="status">Hors ligne : dossiers tels qu'ils étaient le {{ copieDu() | date:'d MMM à HH:mm' }}.</p>
    }
    @if (erreur()) { <p class="erreur" role="alert">{{ erreur() }}</p> }
    @if (message()) { <p class="info" role="status">{{ message() }}</p> }
    @if (chargement()) {
      <p class="discret">Chargement…</p>
    } @else if (!ouverts().length) {
      <p class="discret">Aucun dossier ouvert pour vos équipes.</p>
    }
    @for (d of ouverts(); track d.id) {
      <article class="dossier">
        <button type="button" class="tete" (click)="basculer(d)" [attr.aria-expanded]="ouvert() === d.id">
          <span class="numero">{{ d.numero }}</span>
          <span class="titre">{{ d.titre }}</span>
          <span class="material-icons" aria-hidden="true">{{ ouvert() === d.id ? 'expand_less' : 'expand_more' }}</span>
        </button>
        <p class="discret">{{ d.crise_nom }}@if (d.equipe_nom) { · {{ d.equipe_nom }} }@if (d.commune) { · {{ d.commune }} }</p>
        @if (ouvert() === d.id) {
          @if (d.description) { <p class="description">{{ d.description }}</p> }
          <label class="photo">
            <input type="file" accept="image/*" capture="environment" (change)="photographier(d, $event)" [disabled]="enCours()">
            <span class="material-icons" aria-hidden="true">photo_camera</span>
            {{ enCours() ? 'Préparation de la photo…' : 'Prendre une photo' }}
          </label>
          <p class="discret petit">La photo est datée, située et scellée sur ce téléphone ; le serveur vérifie qu'il reçoit exactement les mêmes octets.</p>
          @if (photos()[d.id]; as liste) {
            @if (liste.length) {
              <ul class="photos">
                @for (p of liste; track p.id) {
                  <li>
                    <span class="material-icons" aria-hidden="true">image</span>
                    <span>{{ p.auteur_nom }} · {{ p.date_upload | date:'d MMM HH:mm' }}@if (p.commentaire) { · {{ p.commentaire }} }</span>
                    @if (p.sha256) { <code [title]="p.sha256">{{ p.sha256.slice(0, 12) }}…</code> }
                  </li>
                }
              </ul>
            } @else {
              <p class="discret">Aucune photo pour l'instant.</p>
            }
          }
        }
      </article>
    }
  `,
  styles: [`
    h1 { font-size: 1.25rem; margin: 4px 0 12px; }
    .dossier { background: var(--ac-surface, #fff); border: 1px solid var(--ac-border, #e5e7eb); border-radius: 12px;
               padding: 10px 14px; margin-bottom: 10px; }
    .tete { display: flex; align-items: center; gap: 8px; width: 100%; background: none; border: 0; padding: 4px 0;
            font: inherit; color: inherit; text-align: left; cursor: pointer; min-height: 44px; }
    .numero { font-size: .75rem; font-weight: 600; color: var(--ac-text-muted, #6b7280); white-space: nowrap; }
    .titre { flex: 1; font-weight: 600; }
    .description { white-space: pre-line; margin: 6px 0; }
    .photo { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 8px; padding: 12px;
             border-radius: 10px; background: var(--brand-primary, #2563eb); color: #fff; font-weight: 600; cursor: pointer; }
    .photo input { position: absolute; width: 1px; height: 1px; opacity: 0; }
    .photo:focus-within { outline: 2px solid var(--brand-primary, #2563eb); outline-offset: 2px; }
    .photos { list-style: none; padding: 0; margin: 8px 0 0; }
    .photos li { display: flex; align-items: center; gap: 8px; padding: 6px 0; font-size: .85rem;
                 border-top: 1px solid var(--ac-border, #e5e7eb); }
    .photos li span:nth-child(2) { flex: 1; }
    code { font-size: .72rem; color: var(--ac-text-muted, #6b7280); }
    .discret { color: var(--ac-text-muted, #6b7280); font-size: .85rem; margin: 4px 0; }
    .petit { font-size: .75rem; }
    .erreur { color: var(--ac-red-text, #b91c1c); }
    .info { background: var(--ac-blue-bg, #dbeafe); color: var(--ac-blue-text, #1e40af); border-radius: 8px; padding: 8px 10px; font-size: .85rem; }
    .copie { background: var(--ac-amber-bg, #fef3c7); color: var(--ac-amber-text, #92400e); border-radius: 8px;
             padding: 8px 10px; font-size: .85rem; }
  `],
})
export class TerrainDossiersComponent implements OnInit {
  private http = inject(HttpClient);
  private horsLigne = inject(HorsLigneService);
  private photosTerrain = inject(PhotosTerrainService);
  readonly dossiers = signal<Dossier[]>([]);
  readonly ouverts = computed(() => this.dossiers().filter(d => !STATUTS_CLOS.includes(d.statut)));
  readonly photos = signal<Record<string, PhotoDossier[]>>({});
  readonly ouvert = signal<string | null>(null);
  readonly copieDu = signal<string | null>(null);
  readonly chargement = signal(true);
  readonly erreur = signal<string | null>(null);
  readonly message = signal<string | null>(null);
  readonly enCours = signal(false);

  ngOnInit(): void { this.charger(); }

  async charger(): Promise<void> {
    try {
      const dossiers = await firstValueFrom(this.http.get<Dossier[]>(`${environment.apiUrl}/dossiers/`));
      this.horsLigne.garder('dossiers', dossiers).catch(() => {});
      this.dossiers.set(dossiers);
      this.copieDu.set(null);
    } catch (e) {
      const copie = HorsLigneService.estHorsLigne(e) ? await this.horsLigne.relire<Dossier[]>('dossiers') : null;
      if (copie) { this.dossiers.set(copie.valeur); this.copieDu.set(copie.enregistree_le); }
      else this.erreur.set('Impossible de charger les dossiers. Vérifiez le réseau, puis réessayez.');
    }
    this.chargement.set(false);
  }

  basculer(d: Dossier): void {
    this.ouvert.set(this.ouvert() === d.id ? null : d.id);
    if (this.ouvert() === d.id) this.chargerPhotos(d.id);
  }

  private async chargerPhotos(id: string): Promise<void> {
    try {
      const liste = await firstValueFrom(this.http.get<PhotoDossier[]>(`${environment.apiUrl}/documents/`, { params: { dossier: id } }));
      this.photos.update(p => ({ ...p, [id]: liste }));
    } catch { /* sans réseau : la liste reste celle d'avant, ou absente */ }
  }

  async photographier(d: Dossier, evenement: Event): Promise<void> {
    const champ = evenement.target as HTMLInputElement;
    const fichier = champ.files?.[0];
    champ.value = '';
    if (!fichier) return;
    this.enCours.set(true);
    this.message.set(null);
    this.erreur.set(null);
    try {
      const r = await this.photosTerrain.prendre(fichier, { genre: 'photo_dossier', dossier: d.id }, '', `Photo — ${d.titre}`);
      this.message.set((r.sansLieu ? 'Photo enregistrée sans position (position refusée ou indisponible). ' : 'Photo enregistrée. ')
        + (this.horsLigne.enLigne() ? 'Envoi en cours.' : 'Elle partira au retour du réseau.'));
      await this.horsLigne.envoyer();
      this.chargerPhotos(d.id);
    } catch {
      this.erreur.set('Cette photo n\'a pas pu être lue. Reprenez-la.');
    } finally {
      this.enCours.set(false);
    }
  }
}
