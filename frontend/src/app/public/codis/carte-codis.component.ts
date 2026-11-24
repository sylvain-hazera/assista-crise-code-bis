import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ActivatedRoute } from '@angular/router';
import maplibregl from 'maplibre-gl';

import { environment } from '../../../environments/environment';
import { styleCarte } from '../../shared/utils/carte-style';

interface PointCodis {
  id: string; nom: string; type_pei: string; debit: number | null; volume: number | null;
  latitude: number; longitude: number; statut: string; statut_libelle: string; indicatif: string | null;
  actif_le: string | null; ferme_le: string | null; demande_le: string;
  lambert93?: { x: number; y: number };
}
interface CarteCodis { crise: string; maj: string; actifs: number; points: PointCodis[]; centre: { latitude: number; longitude: number }; }

/** Couleur d'un point sur la carte du CODIS : vert actif, orange en préparation, gris fermé. */
export function couleurCodis(statut: string): string {
  return statut === 'ACTIF' ? '#15803d' : statut === 'FERME' ? '#9ca3af' : '#f59e0b';
}

/**
 * La carte des points d'eau d'une crise feu, pour le CODIS, sans compte (24/11/2026). Le lien
 * porte un jeton que la cellule peut révoquer. Aucun nom de personne : des points, leur état,
 * l'indicatif de l'équipe. Relue toutes les 30 s.
 */
@Component({
  selector: 'app-carte-codis',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  template: `
    <main class="codis">
      @if (erreur()) {
        <h1>Points d'eau</h1>
        <p class="erreur">{{ erreur() }}</p>
      } @else if (carte()) {
        <h1>Points d'eau — {{ carte()!.crise }}</h1>
        <p class="maj"><strong>{{ carte()!.actifs }}</strong> point(s) actif(s), remplissage possible · relu à {{ carte()!.maj | date:'HH:mm:ss' }}</p>
      } @else {
        <h1>Points d'eau</h1>
        <p class="maj">Chargement…</p>
      }
      <div #carteHote class="carte" [hidden]="!!erreur()"></div>
      @if (carte(); as c) {
        <ul class="liste">
          @for (p of c.points; track p.id) {
            <li [attr.data-statut]="p.statut">
              <span class="pastille" [style.background]="couleur(p.statut)"></span>
              <div>
                <strong>{{ p.nom }}</strong> — {{ p.statut_libelle }}
                @if (p.statut === 'ACTIF' && p.actif_le) { depuis {{ p.actif_le | date:'HH:mm' }} }
                @if (p.statut === 'FERME' && p.ferme_le) { à {{ p.ferme_le | date:'HH:mm' }} }
                <br><span class="detail">
                  GPS {{ p.latitude | number:'1.5-5' }}, {{ p.longitude | number:'1.5-5' }}
                  @if (p.lambert93) { · Lambert 93 X {{ p.lambert93.x }} Y {{ p.lambert93.y }} }
                  @if (p.debit) { · {{ p.debit | number:'1.0-0' }} m³/h }@if (p.volume) { · {{ p.volume | number:'1.0-0' }} m³ }
                  @if (p.indicatif) { · équipe {{ p.indicatif }} }
                  · <a [href]="'https://www.openstreetmap.org/?mlat=' + p.latitude + '&mlon=' + p.longitude + '#map=17/' + p.latitude + '/' + p.longitude" target="_blank" rel="noopener">itinéraire</a>
                </span>
              </div>
            </li>
          } @empty {
            <li>Aucun point d'eau ouvert pour l'instant.</li>
          }
        </ul>
      }
      <p class="pied">Assista-Crise · lien remis par la cellule de crise de la commune, révocable.</p>
    </main>
  `,
  styles: [`
    .codis { max-width: 64rem; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: .75rem; font-family: inherit; }
    h1 { margin: 0; font-size: 1.4rem; }
    .maj { margin: 0; color: #374151; }
    .erreur { padding: .75rem 1rem; border-radius: 8px; background: #fef2f2; color: #b91c1c; }
    .carte { height: 55vh; min-height: 18rem; border-radius: 10px; overflow: hidden; border: 1px solid #e5e7eb; }
    .liste { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .4rem; }
    .liste li { display: flex; gap: .6rem; align-items: flex-start; padding: .6rem .75rem; border: 1px solid #e5e7eb; border-radius: 8px; }
    .liste li[data-statut='FERME'] { opacity: .6; }
    .pastille { flex: none; width: 14px; height: 14px; border-radius: 50%; margin-top: .25rem; }
    .detail { color: #6b7280; font-size: .85rem; font-variant-numeric: tabular-nums; }
    .pied { color: #6b7280; font-size: .8rem; }
  `],
})
export class CarteCodisComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('carteHote') carteHote?: ElementRef<HTMLDivElement>;
  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  readonly carte = signal<CarteCodis | null>(null);
  readonly erreur = signal<string | null>(null);
  private map?: maplibregl.Map;
  private marqueurs: maplibregl.Marker[] = [];
  private minuterie?: ReturnType<typeof setInterval>;
  private cadree = false;
  readonly couleur = couleurCodis;

  ngOnInit(): void {
    this.relire();
    this.minuterie = setInterval(() => this.relire(), 30_000);
  }

  ngAfterViewInit(): void {
    if (!this.carteHote) return;
    try {
      this.map = new maplibregl.Map({ container: this.carteHote.nativeElement, style: styleCarte(), center: [2.5, 46.5], zoom: 5 });
      this.map.on('load', () => this.dessiner());
    } catch {
      this.map = undefined;   // sans WebGL : la liste suffit
    }
  }

  ngOnDestroy(): void {
    if (this.minuterie) clearInterval(this.minuterie);
    this.map?.remove();
  }

  private relire(): void {
    const jeton = this.route.snapshot.paramMap.get('jeton') || '';
    this.http.get<CarteCodis>(`${environment.apiUrl}/public/codis/${encodeURIComponent(jeton)}/`).subscribe({
      next: c => { this.carte.set(c); this.erreur.set(null); this.dessiner(); },
      error: e => this.erreur.set(e?.status === 404 ? 'Ce lien n\'est plus valable : demandez-en un nouveau à la cellule de crise.'
                                                    : 'La carte n\'a pas pu être relue. Nouvel essai dans 30 secondes.'),
    });
  }

  private dessiner(): void {
    const c = this.carte();
    if (!this.map || !c) return;
    this.marqueurs.forEach(m => m.remove());
    this.marqueurs = c.points.map(p => new maplibregl.Marker({ color: couleurCodis(p.statut) })
      .setLngLat([p.longitude, p.latitude])
      .setPopup(new maplibregl.Popup().setText(`${p.nom} — ${p.statut_libelle}`))
      .addTo(this.map!));
    if (!this.cadree) {
      this.cadree = true;
      if (c.points.length > 1) {
        const bornes = new maplibregl.LngLatBounds();
        c.points.forEach(p => bornes.extend([p.longitude, p.latitude]));
        this.map.fitBounds(bornes, { padding: 60, maxZoom: 15 });
      } else {
        const p = c.points[0] ?? c.centre;
        this.map.jumpTo({ center: [p.longitude, p.latitude], zoom: 13 });
      }
    }
  }
}
