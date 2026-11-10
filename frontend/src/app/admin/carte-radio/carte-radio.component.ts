import { AfterViewInit, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import maplibregl from 'maplibre-gl';
import type { FeatureCollection, Geometry } from 'geojson';

import { styleCarte } from '../../shared/utils/carte-style';
import { RelaisMeshCoreService } from '../../services/relais-meshcore.service';
import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { ContactMeshCoreService } from '../../services/contact-meshcore.service';
import { ContactMeshtasticService } from '../../services/contact-meshtastic.service';
import { LiaisonMeshtasticService } from '../../services/liaison-meshtastic.service';
import { CouvertureRadioService } from '../../services/couverture-radio.service';
import { CouvertureRadioSite } from '../../shared/models/couverture-radio.model';

interface CalquesRadio {
  passerelles: boolean;
  relais: boolean;
  repeteursEntendus: boolean;
  noeudsMeshtastic: boolean;
  liaisons: boolean;
  couverture: boolean;
}

/** La carte du réseau radio : l'infrastructure, ce qu'elle entend, et jusqu'où ça porte.
 *
 * Séparée de `/admin/carte` à la demande du 10/11/2026. La carte générale est celle de la
 * crise : demandes, offres, centres, et les positions des intervenants en mission. Y empiler
 * six calques radio la rendait illisible pour qui cherche un hébergement, et illisible pour qui
 * cherche un relais sourd. Les deux cartes ne répondent pas à la même question.
 *
 * Ce qui reste sur la carte générale, et qui n'est PAS ici : les positions des intervenants en
 * mission portant leur nœud personnel. Elles appartiennent à la conduite d'opération, pas à
 * l'exploitation du réseau.
 *
 * Deux calques sont chargés à la première activation et non au démarrage : les liaisons
 * mesurées (le plus volumineux à l'échelle d'un département) et la couverture calculée (des
 * milliers de points par site). */
@Component({
  selector: 'app-carte-radio',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './carte-radio.component.html',
  styleUrl: './carte-radio.component.scss',
})
export class CarteRadioComponent implements OnInit, AfterViewInit, OnDestroy {

  @ViewChild('conteneurCarte') conteneurCarte!: ElementRef;

  /** Vrai quand le navigateur n'a pas pu fournir de contexte WebGL : le gabarit affiche alors un
   * message au lieu d'un cadre vide. Sans ce garde, l'exception du constructeur traverse
   * ngAfterViewInit et la PAGE ENTIÈRE reste blanche (voir map.component.ts). */
  carteIndisponible = false;

  panneauOuvert = true;

  calques: CalquesRadio = {
    passerelles: true,
    relais: true,
    repeteursEntendus: true,
    noeudsMeshtastic: true,
    // Chargés à la première activation : voir la docstring de la classe.
    liaisons: false,
    couverture: false,
  };

  /** Couvertures calculées et terminées, pour le sélecteur. */
  couvertures: CouvertureRadioSite[] = [];
  couvertureChoisie: string | null = null;

  /** Compteurs affichés dans le panneau : une carte vide ne dit pas si elle est vide parce
   * qu'il n'y a rien, ou parce que le chargement a échoué. */
  comptes: Record<keyof CalquesRadio, number | null> = {
    passerelles: null, relais: null, repeteursEntendus: null,
    noeudsMeshtastic: null, liaisons: null, couverture: null,
  };
  erreurs: string[] = [];

  private carte: maplibregl.Map | null = null;
  private cartePrete = false;
  private enAttenteDeCarte: (() => void)[] = [];

  private donnees: Partial<Record<keyof CalquesRadio, FeatureCollection<Geometry>>> = {};
  private liaisonsChargees = false;

  constructor(private relaisService: RelaisMeshCoreService,
              private compagnonService: CompagnonMeshCoreService,
              private contactMeshCoreService: ContactMeshCoreService,
              private contactMeshtasticService: ContactMeshtasticService,
              private liaisonService: LiaisonMeshtasticService,
              private couvertureService: CouvertureRadioService) {}

  ngOnInit(): void {
    this.chargerPasserelles();
    this.chargerRelais();
    this.chargerRepeteursEntendus();
    this.chargerNoeudsMeshtastic();
    this.chargerListeCouvertures();
  }

  ngAfterViewInit(): void {
    try {
      this.carte = new maplibregl.Map({
        container: this.conteneurCarte.nativeElement,
        style: styleCarte(),
        center: [2.5, 46.6],
        zoom: 5,
        attributionControl: false,
      });
    } catch (erreur) {
      console.warn('Carte radio indisponible : contexte WebGL impossible à créer.', erreur);
      // Au tour suivant : on est dans ngAfterViewInit, la détection de changement de ce cycle
      // est passée et l'écrire tout de suite déclenche NG0100.
      Promise.resolve().then(() => this.carteIndisponible = true);
      return;
    }
    this.carte.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    this.carte.once('load', () => {
      this.cartePrete = true;
      for (const action of this.enAttenteDeCarte) action();
      this.enAttenteDeCarte = [];
    });
  }

  ngOnDestroy(): void {
    this.carte?.remove();
    this.carte = null;
  }

  private quandCartePrete(action: () => void): void {
    if (this.cartePrete) action();
    else this.enAttenteDeCarte.push(action);
  }

  private signaler(message: string): void {
    if (!this.erreurs.includes(message)) this.erreurs.push(message);
  }

  // ── Chargements ───────────────────────────────────────────────────────────

  /** Passerelles MeshCore : position saisie à la main dans /admin/meshcore-companions. */
  private chargerPasserelles(): void {
    this.compagnonService.getAll().subscribe({
      next: (compagnons) => {
        const avecPosition = compagnons.filter(c => c.actif && c.latitude != null && c.longitude != null);
        this.comptes.passerelles = avecPosition.length;
        this.donnees.passerelles = {
          type: 'FeatureCollection',
          features: avecPosition.map(c => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(c.longitude), Number(c.latitude)] },
            properties: { nom: c.nom, detail: 'Passerelle MeshCore' },
          })),
        };
        this.quandCartePrete(() => this.poserCalquePoints('passerelles', '#ea580c', '#c2410c', 7));
      },
      error: () => this.signaler('Passerelles indisponibles.'),
    });
  }

  /** Répéteurs déclarés à la main — infrastructure voulue, par opposition à ce qu'on entend. */
  private chargerRelais(): void {
    this.relaisService.getAll().subscribe({
      next: (relais) => {
        const avecPosition = relais.filter(r => r.actif && r.latitude != null && r.longitude != null);
        this.comptes.relais = avecPosition.length;
        this.donnees.relais = {
          type: 'FeatureCollection',
          features: avecPosition.map(r => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(r.longitude), Number(r.latitude)] },
            properties: { nom: r.nom, detail: 'Relais déclaré' },
          })),
        };
        this.quandCartePrete(() => this.poserCalquePoints('relais', '#0891b2', '#0e7490', 6));
      },
      error: () => this.signaler('Relais déclarés indisponibles.'),
    });
  }

  /** Répéteurs et room servers ENTENDUS sur l'air (ContactMeshCore) : la vraie carte du réseau,
   * par opposition aux relais saisis. Seuls REPEATER et ROOM — un COMPANION peut être le
   * terminal d'une personne, et un SENSOR n'est pas un relais (même filtrage que la fédération,
   * core/federation_carte_live.py). */
  private chargerRepeteursEntendus(): void {
    this.contactMeshCoreService.getAll().subscribe({
      next: (contacts) => {
        const retenus = contacts.filter(
          c => (c.type_contact === 'REPEATER' || c.type_contact === 'ROOM')
            && c.latitude != null && c.longitude != null,
        );
        this.comptes.repeteursEntendus = retenus.length;
        this.donnees.repeteursEntendus = {
          type: 'FeatureCollection',
          features: retenus.map(c => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(c.longitude), Number(c.latitude)] },
            properties: {
              nom: c.nom || c.pubkey_hex.slice(0, 8),
              detail: (c.type_contact === 'ROOM' ? 'Room server entendu' : 'Répéteur entendu')
                // `sauts` reste absent plutôt que 0 quand aucun chemin n'est confirmé :
                // « 0 saut » laisserait croire à une liaison directe.
                + (c.nombre_sauts != null ? ` — ${c.nombre_sauts} saut(s)` : '')
                + (c.niveau_batterie_pct != null ? ` — batterie ${c.niveau_batterie_pct} %` : ''),
            },
          })),
        };
        this.quandCartePrete(() => this.poserCalquePoints('repeteursEntendus', '#9333ea', '#6b21a8', 5));
      },
      error: () => this.signaler('Répéteurs entendus indisponibles.'),
    });
  }

  /** Nœuds Meshtastic découverts passivement sur MQTT, avec position annoncée. */
  private chargerNoeudsMeshtastic(): void {
    this.contactMeshtasticService.getAll().subscribe({
      next: (contacts) => {
        const retenus = contacts.filter(c => c.latitude != null && c.longitude != null);
        this.comptes.noeudsMeshtastic = retenus.length;
        this.donnees.noeudsMeshtastic = {
          type: 'FeatureCollection',
          features: retenus.map(c => ({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [Number(c.longitude), Number(c.latitude)] },
            properties: {
              nom: c.long_name || c.short_name || c.node_num.toString(16).padStart(8, '0'),
              detail: `Nœud Meshtastic entendu par « ${c.compagnon_nom ?? 'une passerelle'} »`,
            },
          })),
        };
        this.quandCartePrete(() => this.poserCalquePoints('noeudsMeshtastic', '#2563eb', '#1d4ed8', 5));
      },
      error: () => this.signaler('Nœuds Meshtastic indisponibles.'),
    });
  }

  private chargerLiaisons(): void {
    this.liaisonService.geojson().subscribe({
      next: (collection) => {
        const donnees = collection as unknown as FeatureCollection<Geometry>;
        this.donnees.liaisons = donnees;
        this.comptes.liaisons = donnees.features.length;
        this.quandCartePrete(() => this.poserCalqueLiaisons());
      },
      error: () => this.signaler('Liaisons mesurées indisponibles.'),
    });
  }

  private chargerListeCouvertures(): void {
    this.couvertureService.couvertures().subscribe({
      next: (couvertures) => {
        this.couvertures = couvertures.filter(c => c.statut === 'TERMINEE' && c.nombre_points > 0);
      },
      error: () => { this.couvertures = []; },
    });
  }

  /** Points atteints de la couverture choisie. Des points et non un contour : une couverture
   * radio est trouée, un contour déclarerait couvert ce qu'il englobe. */
  chargerCouverture(): void {
    if (!this.couvertureChoisie) {
      this.calques.couverture = false;
      return;
    }
    this.couvertureService.geojson(this.couvertureChoisie).subscribe({
      next: (collection) => {
        const donnees = collection as unknown as FeatureCollection<Geometry>;
        this.donnees.couverture = donnees;
        this.comptes.couverture = donnees.features.length;
        this.calques.couverture = true;
        this.quandCartePrete(() => this.poserCalqueCouverture());
      },
      error: () => this.signaler('Couverture indisponible.'),
    });
  }

  // ── Calques ───────────────────────────────────────────────────────────────

  /** Points + libellés + infobulle, pour les quatre calques de même forme. Les paramètres
   * couvrent tout ce qui les distingue, plutôt que quatre méthodes identiques à une couleur
   * près — c'est le copier-coller que `map.component.ts` assume faute d'abstraction, et il n'y
   * a pas de raison de le refaire ici. */
  private poserCalquePoints(cle: keyof CalquesRadio, couleur: string, couleurTexte: string,
                            rayon: number): void {
    const donnees = this.donnees[cle];
    if (!this.carte || !donnees) return;

    const source = this.carte.getSource(cle) as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(donnees);
      return;
    }
    this.carte.addSource(cle, { type: 'geojson', data: donnees });
    const visibility = this.calques[cle] ? 'visible' : 'none';

    this.carte.addLayer({
      id: `${cle}-points`,
      type: 'circle',
      source: cle,
      layout: { visibility },
      paint: {
        // Couleurs lisibles sur fond CLAIR uniquement : le fond de carte ne suit pas le mode
        // sombre (namedFlavor('light') codé en dur, DOCUMENTATION.md § 6.3).
        'circle-color': couleur,
        'circle-radius': rayon,
        'circle-stroke-width': 2,
        'circle-stroke-color': '#fff',
      },
    });
    this.carte.addLayer({
      id: `${cle}-label`,
      type: 'symbol',
      source: cle,
      layout: {
        visibility,
        'text-field': ['get', 'nom'],
        'text-size': 11,
        'text-offset': [0, 1.2],
        'text-anchor': 'top',
      },
      paint: { 'text-color': couleurTexte, 'text-halo-color': '#fff', 'text-halo-width': 1 },
    });

    this.carte.on('click', `${cle}-points`, (e) => {
      if (!e.features?.length) return;
      const geometrie = e.features[0].geometry as GeoJSON.Point;
      const proprietes = e.features[0].properties || {};
      new maplibregl.Popup()
        .setLngLat(geometrie.coordinates.slice() as [number, number])
        .setHTML(`<strong>${proprietes['nom']}</strong><br>${proprietes['detail']}`)
        .addTo(this.carte!);
    });
    this.carte.on('mouseenter', `${cle}-points`, () => { this.carte!.getCanvas().style.cursor = 'pointer'; });
    this.carte.on('mouseleave', `${cle}-points`, () => { this.carte!.getCanvas().style.cursor = ''; });
  }

  private poserCalqueLiaisons(): void {
    if (!this.carte || !this.donnees.liaisons) return;
    const source = this.carte.getSource('liaisons') as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(this.donnees.liaisons);
      return;
    }
    this.carte.addSource('liaisons', { type: 'geojson', data: this.donnees.liaisons });

    // `before` EXPLICITE : les traits doivent passer SOUS les points, sinon ils les barrent et
    // on ne peut plus cliquer dessus. MapLibre empile dans l'ordre d'ajout, et les calques
    // arrivent au gré des réponses HTTP — d'où la garde getLayer(), MapLibre levant sur un
    // calque inexistant.
    const dessous = ['passerelles-points', 'relais-points', 'repeteursEntendus-points',
                     'noeudsMeshtastic-points'].find(id => this.carte!.getLayer(id));

    this.carte.addLayer({
      id: 'liaisons-traits',
      type: 'line',
      source: 'liaisons',
      layout: { visibility: this.calques.liaisons ? 'visible' : 'none' },
      paint: {
        // Un SNR sous -10 dB est à la limite de la démodulation (seuil LONG_FAST ≈ -17,5 dB),
        // au-dessus de 0 dB la liaison est confortable.
        'line-color': [
          'case',
          ['==', ['get', 'snr'], null], '#9ca3af',
          ['<', ['get', 'snr'], -10], '#dc2626',
          ['<', ['get', 'snr'], 0], '#f59e0b',
          '#16a34a',
        ],
        'line-width': ['interpolate', ['linear'], ['get', 'nombre'], 1, 1, 50, 3.5],
        'line-opacity': 0.65,
      },
    }, dessous);

    this.carte.on('click', 'liaisons-traits', (e) => {
      if (!e.features?.length) return;
      const p = e.features[0].properties || {};
      const snr = p['snr'] != null ? `${p['snr']} dB` : 'SNR inconnu';
      const origine = p['source'] === 'VOISINAGE' ? 'voisinage déclaré'
        : p['source'] === 'TRACEROUTE' ? 'saut de traceroute' : 'reçu par une passerelle';
      const distance = p['distance_km'] != null ? `<br>${p['distance_km']} km` : '';
      new maplibregl.Popup().setLngLat(e.lngLat)
        .setHTML(`<strong>Liaison mesurée</strong><br>${snr} — ${p['nombre']} observation(s)`
                 + `<br><em>${origine}</em>${distance}`)
        .addTo(this.carte!);
    });
  }

  private poserCalqueCouverture(): void {
    if (!this.carte || !this.donnees.couverture) return;
    const source = this.carte.getSource('couverture') as maplibregl.GeoJSONSource | undefined;
    if (source) {
      source.setData(this.donnees.couverture);
      return;
    }
    this.carte.addSource('couverture', { type: 'geojson', data: this.donnees.couverture });

    // Sous tout le reste : c'est un fond, pas un objet. Même garde getLayer() que les liaisons.
    const dessous = ['liaisons-traits', 'passerelles-points', 'relais-points']
      .find(id => this.carte!.getLayer(id));

    this.carte.addLayer({
      id: 'couverture-points',
      type: 'circle',
      source: 'couverture',
      layout: { visibility: this.calques.couverture ? 'visible' : 'none' },
      paint: {
        // Couleur par marge de liaison : sous 3 dB, « ça passe » est une illusion de calcul,
        // le moindre obstacle ou feuillage la mange.
        'circle-color': [
          'case',
          ['<', ['get', 'marge_db'], 3], '#f59e0b',
          ['<', ['get', 'marge_db'], 10], '#65a30d',
          '#15803d',
        ],
        'circle-radius': 3,
        'circle-opacity': 0.55,
      },
    }, dessous);
  }

  // ── Panneau des calques ───────────────────────────────────────────────────

  basculerCalque(): void {
    if (this.calques.liaisons && !this.liaisonsChargees) {
      this.liaisonsChargees = true;
      this.chargerLiaisons();
    }
    if (this.calques.couverture && !this.donnees.couverture) {
      this.chargerCouverture();
      return;
    }
    this.appliquer('passerelles-points', this.calques.passerelles);
    this.appliquer('passerelles-label', this.calques.passerelles);
    this.appliquer('relais-points', this.calques.relais);
    this.appliquer('relais-label', this.calques.relais);
    this.appliquer('repeteursEntendus-points', this.calques.repeteursEntendus);
    this.appliquer('repeteursEntendus-label', this.calques.repeteursEntendus);
    this.appliquer('noeudsMeshtastic-points', this.calques.noeudsMeshtastic);
    this.appliquer('noeudsMeshtastic-label', this.calques.noeudsMeshtastic);
    this.appliquer('liaisons-traits', this.calques.liaisons);
    this.appliquer('couverture-points', this.calques.couverture);
  }

  /** Changement de couverture choisie : on remplace la source plutôt que d'empiler un calque
   * par site, deux couvertures superposées ne se lisant pas. */
  changerCouverture(): void {
    this.donnees.couverture = undefined;
    this.comptes.couverture = null;
    if (this.couvertureChoisie) this.chargerCouverture();
  }

  private appliquer(idCalque: string, visible: boolean): void {
    // MapLibre lève sur un calque inexistant, et les calques arrivent au gré des réponses HTTP.
    if (this.carte?.getLayer(idCalque)) {
      this.carte.setLayoutProperty(idCalque, 'visibility', visible ? 'visible' : 'none');
    }
  }
}
