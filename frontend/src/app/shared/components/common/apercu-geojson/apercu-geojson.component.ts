import { AfterViewInit, ChangeDetectorRef, Component, ElementRef, Input, OnChanges, OnDestroy, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import maplibregl from 'maplibre-gl';

import { styleCarte } from '../../../utils/carte-style';

/** Une couche à montrer : un nom, une couleur, et son contenu GeoJSON. */
export interface CoucheAffichee {
  cle: string;
  nom: string;
  couleur: string;
  donnees: GeoJSON.FeatureCollection;
}

/**
 * Montre des couches GeoJSON sur une carte (18/11/2026) : surfaces, lignes et points, plusieurs
 * couches à la fois, cadrage sur l'ensemble, et les attributs d'un objet au clic.
 *
 * Fait pour la page « Couches cartographiques » : voir un fichier AVANT de le télécharger ou de
 * l'importer. Ne charge rien lui-même : il affiche ce qu'on lui donne.
 */
@Component({
  selector: 'app-apercu-geojson',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (indisponible) { <p class="indisponible">La carte ne peut pas s'afficher sur ce poste (WebGL indisponible). Les fichiers restent téléchargeables.</p> }
    <div #conteneur class="carte" [class.cachee]="indisponible"></div>`,
  styles: [`.carte { width: 100%; height: 26rem; border-radius: 8px; overflow: hidden; border: 1px solid var(--ac-border, #e5e7eb); }
    .cachee { display: none; } .indisponible { color: var(--ac-text-muted, #6b7280); font-size: .9rem; }`],
})
export class ApercuGeojsonComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('conteneur', { static: true }) conteneur!: ElementRef<HTMLDivElement>;
  @Input() couches: CoucheAffichee[] = [];

  indisponible = false;
  private carte: maplibregl.Map | null = null;
  private prete = false;
  private posees = new Set<string>();

  constructor(private detection: ChangeDetectorRef) {}

  ngAfterViewInit(): void {
    try {
      this.carte = new maplibregl.Map({ container: this.conteneur.nativeElement, style: styleCarte(), center: [2.2137, 46.2276], zoom: 5 });
    } catch {
      this.indisponible = true;    // pas de WebGL : on le dit, on ne casse pas la page
      this.detection.detectChanges();
      return;
    }
    this.carte.addControl(new maplibregl.NavigationControl(), 'top-right');
    this.carte.on('load', () => { this.prete = true; this.dessiner(); });
  }

  ngOnChanges(): void { if (this.prete) this.dessiner(); }

  ngOnDestroy(): void { this.carte?.remove(); }

  /** Pose les couches demandées, retire celles qui ne le sont plus, et cadre sur l'ensemble. */
  private dessiner(): void {
    const carte = this.carte;
    if (!carte) return;
    const voulues = new Set(this.couches.map(c => c.cle));
    for (const cle of [...this.posees].filter(c => !voulues.has(c))) {
      for (const suffixe of ['surface', 'ligne', 'point']) if (carte.getLayer(`${cle}-${suffixe}`)) carte.removeLayer(`${cle}-${suffixe}`);
      if (carte.getSource(cle)) carte.removeSource(cle);
      this.posees.delete(cle);
    }
    const bornes = new maplibregl.LngLatBounds();
    let quelqueChose = false;
    for (const couche of this.couches) {
      const source = carte.getSource(couche.cle) as maplibregl.GeoJSONSource | undefined;
      if (source) source.setData(couche.donnees);
      else {
        carte.addSource(couche.cle, { type: 'geojson', data: couche.donnees });
        carte.addLayer({ id: `${couche.cle}-surface`, type: 'fill', source: couche.cle, filter: ['==', ['geometry-type'], 'Polygon'],
          paint: { 'fill-color': couche.couleur, 'fill-opacity': 0.28 } });
        carte.addLayer({ id: `${couche.cle}-ligne`, type: 'line', source: couche.cle, filter: ['!=', ['geometry-type'], 'Point'],
          paint: { 'line-color': couche.couleur, 'line-width': 2 } });
        carte.addLayer({ id: `${couche.cle}-point`, type: 'circle', source: couche.cle, filter: ['==', ['geometry-type'], 'Point'],
          paint: { 'circle-color': couche.couleur, 'circle-radius': 6, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
        for (const suffixe of ['surface', 'point']) {
          carte.on('click', `${couche.cle}-${suffixe}`, (e) => this.decrire(e, couche.nom));
          carte.on('mouseenter', `${couche.cle}-${suffixe}`, () => { carte.getCanvas().style.cursor = 'pointer'; });
          carte.on('mouseleave', `${couche.cle}-${suffixe}`, () => { carte.getCanvas().style.cursor = ''; });
        }
        this.posees.add(couche.cle);
      }
      for (const objet of couche.donnees.features ?? []) quelqueChose = this.etendre(bornes, objet.geometry) || quelqueChose;
    }
    if (quelqueChose) carte.fitBounds(bornes, { padding: 40, maxZoom: 15, duration: 600 });
  }

  /** Les attributs de l'objet cliqué, tels qu'ils sont dans le fichier. Texte seulement. */
  private decrire(e: maplibregl.MapLayerMouseEvent, nomCouche: string): void {
    const proprietes = e.features?.[0]?.properties ?? {};
    const bulle = document.createElement('div');
    const titre = document.createElement('strong');
    titre.textContent = nomCouche;
    bulle.appendChild(titre);
    for (const [cle, valeur] of Object.entries(proprietes).slice(0, 12)) {
      const ligne = document.createElement('div');
      ligne.textContent = `${cle} : ${String(valeur).slice(0, 120)}`;
      bulle.appendChild(ligne);
    }
    new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setDOMContent(bulle).addTo(this.carte!);
  }

  private etendre(bornes: maplibregl.LngLatBounds, geometrie: GeoJSON.Geometry | null): boolean {
    if (!geometrie) return false;
    let trouve = false;
    const parcourir = (coordonnees: unknown): void => {
      if (Array.isArray(coordonnees) && typeof coordonnees[0] === 'number' && typeof coordonnees[1] === 'number') {
        bornes.extend([coordonnees[0], coordonnees[1]] as [number, number]);
        trouve = true;
      } else if (Array.isArray(coordonnees)) coordonnees.forEach(parcourir);
    };
    if (geometrie.type === 'GeometryCollection') geometrie.geometries.forEach(g => { trouve = this.etendre(bornes, g) || trouve; });
    else parcourir(geometrie.coordinates);
    return trouve;
  }
}
