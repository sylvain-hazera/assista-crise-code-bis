import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type { FeatureCollection, Point } from 'geojson';
import maplibregl from 'maplibre-gl';

import { BilanOuvert, CarteOuverteService, CouvertureOuverte, Propagation } from '../../services/carte-ouverte.service';
import { MapComponent } from '../../shared/components/common/map/map.component';
import { BandeauOuvertComponent } from '../bandeau-ouvert.component';

const COULEURS_ROLE: Record<string, string> = { repeater: '#7c3aed', room: '#0d9488' };

/**
 * `/ouvert/carte` (28/11/2026) : la carte en mode ouvert — météo et veille du composant de
 * carte —, plus ce que cette page pose elle-même : répéteurs et rooms MeshCore, couvertures
 * publiées, conduits troposphériques, et l'outil « Est-ce que ça passe ? ».
 *
 * `?vue=propagation` ouvre la carte sur la propagation, `?vue=liaison` sur l'outil.
 */
@Component({
  selector: 'app-ouvert-carte',
  standalone: true,
  imports: [CommonModule, FormsModule, MapComponent, BandeauOuvertComponent],
  templateUrl: './ouvert-carte.component.html',
  styleUrl: './ouvert-carte.component.scss',
})
export class OuvertCarteComponent implements OnInit, OnDestroy {
  carte: maplibregl.Map | null = null;
  vue: 'carte' | 'propagation' | 'liaison' = 'carte';

  // Radio
  repeteurs = true;
  nombreRepeteurs: number | null = null;
  couvertures: CouvertureOuverte[] = [];
  couvertureChoisie = '';

  // Propagation
  propagation: Propagation | null = null;
  tropo = false;
  echeance = '';

  // Liaison
  liaison = { actif: false, a: null as maplibregl.LngLat | null, b: null as maplibregl.LngLat | null,
              preset: 'LONG_FAST', hauteurA: 6, hauteurB: 2, enCours: false, erreur: '', bilan: null as BilanOuvert | null };
  private marqueursLiaison: maplibregl.Marker[] = [];
  private readonly surClicLiaison = (e: maplibregl.MapMouseEvent) => this.pointDeLiaison(e.lngLat);

  constructor(private service: CarteOuverteService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    const vue = this.route.snapshot.queryParamMap.get('vue');
    this.vue = vue === 'propagation' || vue === 'liaison' ? vue : 'carte';
    this.tropo = this.vue === 'propagation';
    this.service.propagation().subscribe({
      next: p => {
        this.propagation = p;
        this.echeance = this.echeanceProche(p);
        this.poserTropo();
      },
      error: () => this.propagation = null,
    });
    this.service.couvertures().subscribe({ next: c => this.couvertures = c, error: () => this.couvertures = [] });
  }

  ngOnDestroy(): void { this.carte?.off('click', this.surClicLiaison); }

  surCarte(carte: maplibregl.Map): void {
    this.carte = carte;
    this.service.radio().subscribe({
      next: g => { this.nombreRepeteurs = g.features.length; this.poserRadio(g); },
      error: () => this.nombreRepeteurs = null,
    });
    this.poserTropo();
    if (this.vue === 'liaison') this.commencerLiaison();
  }

  // ── Radio ──────────────────────────────────────────────────────────────────────────────

  private poserRadio(g: FeatureCollection<Point>): void {
    const c = this.carte;
    if (!c) return;
    if (!c.getSource('ouvert-radio')) {
      c.addSource('ouvert-radio', { type: 'geojson', data: g });
      c.addLayer({ id: 'ouvert-radio', type: 'circle', source: 'ouvert-radio', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 5, 3, 10, 6, 14, 8],
        'circle-color': ['match', ['get', 'role'], 'room', COULEURS_ROLE['room'], COULEURS_ROLE['repeater']],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.2,
        'circle-opacity': ['case', ['get', 'actif'], 1, 0.55],
      } });
      c.on('click', 'ouvert-radio', e => {
        if (this.liaison.actif) return;
        const p = e.features?.[0]?.properties as Record<string, unknown> | undefined;
        if (!p) return;
        const vu = p['dernier_vu'] ? new Date(String(p['dernier_vu'])).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '—';
        const div = document.createElement('div');
        div.className = 'popup-ouvert';
        const titre = document.createElement('strong');
        titre.textContent = String(p['nom'] ?? '');
        const ligne = document.createElement('div');
        ligne.textContent = `${p['role_libelle']} · ${p['source']}`;
        const date = document.createElement('div');
        date.textContent = `Dernier vu : ${vu}`;
        div.append(titre, ligne, date);
        new maplibregl.Popup().setLngLat(e.lngLat).setDOMContent(div).addTo(c);
      });
      c.on('mouseenter', 'ouvert-radio', () => c.getCanvas().style.cursor = 'pointer');
      c.on('mouseleave', 'ouvert-radio', () => c.getCanvas().style.cursor = '');
    }
    this.basculerRepeteurs();
  }

  basculerRepeteurs(): void {
    if (this.carte?.getLayer('ouvert-radio')) this.carte.setLayoutProperty('ouvert-radio', 'visibility', this.repeteurs ? 'visible' : 'none');
  }

  choisirCouverture(): void {
    const c = this.carte;
    if (!c) return;
    if (c.getLayer('ouvert-couverture')) c.removeLayer('ouvert-couverture');
    if (c.getSource('ouvert-couverture')) c.removeSource('ouvert-couverture');
    if (!this.couvertureChoisie) return;
    this.service.couverture(this.couvertureChoisie).subscribe(g => {
      if (!this.carte || c.getSource('ouvert-couverture')) return;
      c.addSource('ouvert-couverture', { type: 'geojson', data: g });
      c.addLayer({ id: 'ouvert-couverture', type: 'circle', source: 'ouvert-couverture', paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'], 7, 1.5, 12, 4],
        'circle-color': ['step', ['get', 'marge_db'], '#f59e0b', 6, '#16a34a'],
        'circle-opacity': 0.6,
      } }, c.getLayer('ouvert-radio') ? 'ouvert-radio' : undefined);
    });
  }

  get couvertureAffichee(): CouvertureOuverte | undefined { return this.couvertures.find(c => c.id === this.couvertureChoisie); }

  // ── Propagation ───────────────────────────────────────────────────────────────────────

  private echeanceProche(p: Propagation): string {
    const maintenant = Date.now();
    const triees = [...p.tropo.echeances].sort((x, y) =>
      Math.abs(new Date(x.echeance).getTime() - maintenant) - Math.abs(new Date(y.echeance).getTime() - maintenant));
    return triees[0]?.echeance ?? '';
  }

  poserTropo(): void {
    const c = this.carte, p = this.propagation;
    if (!c || !p) return;
    const visible = this.tropo && !!this.echeance;
    const source = c.getSource('ouvert-tropo') as maplibregl.ImageSource | undefined;
    if (!visible) {
      if (c.getLayer('ouvert-tropo')) c.setLayoutProperty('ouvert-tropo', 'visibility', 'none');
      return;
    }
    const url = this.service.imageTropo(this.echeance);
    const coins = p.tropo.coins as [[number, number], [number, number], [number, number], [number, number]];
    if (source) {
      source.updateImage({ url, coordinates: coins });
    } else {
      c.addSource('ouvert-tropo', { type: 'image', url, coordinates: coins });
      c.addLayer({ id: 'ouvert-tropo', type: 'raster', source: 'ouvert-tropo', paint: { 'raster-opacity': 0.75 } },
        c.getLayer('ouvert-radio') ? 'ouvert-radio' : undefined);
    }
    c.setLayoutProperty('ouvert-tropo', 'visibility', 'visible');
  }

  get echeanceAffichee() { return this.propagation?.tropo.echeances.find(e => e.echeance === this.echeance); }

  // ── Est-ce que ça passe ? ─────────────────────────────────────────────────────────────

  commencerLiaison(): void {
    this.effacerLiaison();
    this.liaison.actif = true;
    this.carte?.getCanvas().style.setProperty('cursor', 'crosshair');
    this.carte?.on('click', this.surClicLiaison);
  }

  private pointDeLiaison(point: maplibregl.LngLat): void {
    if (!this.liaison.actif || !this.carte) return;
    const marqueur = new maplibregl.Marker({ color: this.liaison.a ? '#dc2626' : '#2563eb' }).setLngLat(point).addTo(this.carte);
    this.marqueursLiaison.push(marqueur);
    if (!this.liaison.a) { this.liaison.a = point; return; }
    this.liaison.b = point;
    this.liaison.actif = false;
    this.carte.off('click', this.surClicLiaison);
    this.carte.getCanvas().style.removeProperty('cursor');
    this.tracerLigne();
    this.calculerLiaison();
  }

  calculerLiaison(): void {
    const { a, b } = this.liaison;
    if (!a || !b) return;
    this.liaison.enCours = true;
    this.liaison.erreur = '';
    this.liaison.bilan = null;
    this.service.liaison({ lat_a: a.lat, lon_a: a.lng, lat_b: b.lat, lon_b: b.lng, preset: this.liaison.preset,
                           hauteur_a_m: this.liaison.hauteurA, hauteur_b_m: this.liaison.hauteurB }).subscribe({
      next: bilan => { this.liaison.bilan = bilan; this.liaison.enCours = false; },
      error: err => {
        this.liaison.enCours = false;
        this.liaison.erreur = err?.status === 429 ? 'Trop de calculs depuis votre connexion : réessayez dans une minute.'
          : (err?.error?.detail || 'Le calcul n\'a pas abouti.');
      },
    });
  }

  private tracerLigne(): void {
    const c = this.carte, { a, b } = this.liaison;
    if (!c || !a || !b) return;
    const donnees = { type: 'Feature' as const, properties: {}, geometry: { type: 'LineString' as const, coordinates: [[a.lng, a.lat], [b.lng, b.lat]] } };
    const source = c.getSource('ouvert-liaison') as maplibregl.GeoJSONSource | undefined;
    if (source) { source.setData(donnees); return; }
    c.addSource('ouvert-liaison', { type: 'geojson', data: donnees });
    c.addLayer({ id: 'ouvert-liaison', type: 'line', source: 'ouvert-liaison',
                 paint: { 'line-color': '#1d4ed8', 'line-width': 3, 'line-dasharray': [2, 1] } });
  }

  effacerLiaison(): void {
    this.marqueursLiaison.forEach(m => m.remove());
    this.marqueursLiaison = [];
    Object.assign(this.liaison, { actif: false, a: null, b: null, bilan: null, erreur: '', enCours: false });
    const c = this.carte;
    if (c) {
      c.off('click', this.surClicLiaison);
      c.getCanvas().style.removeProperty('cursor');
      if (c.getLayer('ouvert-liaison')) c.removeLayer('ouvert-liaison');
      if (c.getSource('ouvert-liaison')) c.removeSource('ouvert-liaison');
    }
  }

  heure(iso: string): string {
    return new Date(iso).toLocaleString('fr-FR', { weekday: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }

  distanceKm(): string { return this.liaison.bilan ? (this.liaison.bilan.distance_m / 1000).toLocaleString('fr-FR', { maximumFractionDigits: 1 }) : ''; }

  niveau(n: number | null | undefined): string {
    return n === null || n === undefined ? '—' : n === 0 ? 'aucun' : `niveau ${n}`;
  }
}
