import { Component, Input } from '@angular/core';
import { TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { of } from 'rxjs';

import { CarteMeteoComponent } from './carte-meteo.component';
import { MapComponent } from '../../shared/components/common/map/map.component';
import { VeilleService } from '../../services/veille.service';
import { CelluleOrage, FeuxSuivis, OragesRadar, PotentielOrageFeu } from '../../shared/models/veille.model';

/** La carte elle-même (MapLibre, WebGL) est remplacée : on vérifie ici la retranscription. */
@Component({ selector: 'app-map', standalone: true, template: '' })
class CarteFactice {
  @Input() modeMeteo = false;
  centres: [number, number, number][] = [];
  choix: [string | null, boolean][] = [];
  centrerSur(lon: number, lat: number, zoom = 9): void { this.centres.push([lon, lat, zoom]); }
  choisirCellule(identifiant: string | null, centrer = false): void { this.choix.push([identifiant, centrer]); }
}

function cellule(identifiant: string, max: number, extra: Partial<CelluleOrage['releves']> = {}): CelluleOrage {
  return {
    identifiant, distance_km: 12,
    contour: { type: 'Polygon', coordinates: [[[2, 46], [2.2, 46], [2.2, 46.2], [2, 46.2]]] },
    couloir: null,
    releves: {
      intensite_max_mmh: max, intensite_moyenne_mmh: max / 2, libelle: 'pluie intense', surface_km2: 40,
      tendance_mmh: null, communes_sous_la_pluie: [{ code: '42218', nom: 'Saint-Étienne' }],
      rafale_mesuree: null, trace: [], eclairs: 3, suivi: null, doppler: null, ...extra,
    },
    estimations: { cap_deg: 90, vers: "l'est", vitesse_kmh: 45, communes_atteintes: [], ligne_de_grain: false, longueur_km: 12 },
    prevision_meteo_france: { grele: false, rafale_kmh: null, grele_diagnostic_kgm2: null, grele_niveau: null },
  };
}

const AUCUN_FEU: FeuxSuivis = { source: 'EUMETSAT LSA SAF [FRP-PIXEL, LSA-509]', releve_le: null, perime: false,
                                 centre: null, rayon_km: 100, emprise_connue: true, sources_fixes: 0, resultats: [] };
const SANS_POTENTIEL: PotentielOrageFeu = {
  source: 'Météo-France (ARPEGE), nos estimations', releve_le: null, perime: false, nos_estimations: true, calcul: null,
  coins: [], legende: [{ palier: 2, libelle: 'élevé', pft_jusqua_gw: 250, couleur: '#ea580c' }],
  centre: { latitude: 44.87, longitude: -0.98 }, rayon_km: 50, echeances: [],
};

function reponse(cellules: CelluleOrage[], centre: OragesRadar['centre'] = { latitude: 45.44, longitude: 4.39 }): OragesRadar {
  return {
    source: 'Météo-France', releve_le: '2026-11-20T06:10:00Z', perime: false,
    heure_image: '2026-11-20T06:05:00Z', radars: 29, radars_absents: [],
    centre, rayon_km: centre ? 60 : null, couvert: true, cellules,
    cumuls: null, foudre: null, blitzortung: null,
  };
}

describe('CarteMeteoComponent', () => {
  let service: jasmine.SpyObj<VeilleService>;

  function creer() {
    TestBed.configureTestingModule({
      imports: [CarteMeteoComponent],
      providers: [{ provide: VeilleService, useValue: service }],
    }).overrideComponent(CarteMeteoComponent, { remove: { imports: [MapComponent] }, add: { imports: [CarteFactice] } });
    const fixture = TestBed.createComponent(CarteMeteoComponent);
    fixture.detectChanges();
    // pollWhileVisible part d'un timer(0) : un tour d'horloge pour la première lecture.
    tick(0);
    fixture.detectChanges();
    return fixture;
  }

  beforeEach(() => {
    service = jasmine.createSpyObj<VeilleService>('VeilleService', ['orages', 'oragesFrance', 'feuxSuivis', 'potentielOrageFeu']);
    service.feuxSuivis.and.returnValue(of(AUCUN_FEU));
    service.potentielOrageFeu.and.returnValue(of(SANS_POTENTIEL));
  });

  it('retranscrit les feux suivis par satellite et le potentiel d\'orage de feu', fakeAsync(() => {
    service.orages.and.returnValue(of(reponse([])));
    service.feuxSuivis.and.returnValue(of({ ...AUCUN_FEU, resultats: [{
      identifiant: 'f1', latitude: 44.87, longitude: -0.98, distance_km: 12, premier_vu: '2026-07-24T08:00:00Z',
      dernier_vu: '2026-07-24T16:40:00Z', statut: 'actif', puissance_mw: 7560, puissance_max_mw: 27450,
      instant_max: '2026-07-24T12:20:00Z', pixels: 54, confirme: true, source_fixe: false,
      courbe: [['2026-07-24T16:20:00Z', 12170, 60], ['2026-07-24T16:30:00Z', 12000, 58], ['2026-07-24T16:40:00Z', 7560, 54]],
      contexte: {
        orage: { identifiant: 'c1', distance_km: 0, au_dessus: true, intensite_max_mmh: 40, eclairs: 0,
                 rafale_descendante: false, rotation: false, grele: false },
        eclairs_30_min: 0, masque_par_nuage: true,
        potentiel: { pft_gw: 213, c_haines: 9.8, palier: 2, potentiel: 'élevé', echeance: '2026-07-24T15:00:00Z',
                     puissance_estimee_gw: [38, 76], atteint_le_seuil: false },
      },
    }] }));
    service.potentielOrageFeu.and.returnValue(of({ ...SANS_POTENTIEL, echeances: [
      { echeance: '2026-07-24T15:00:00Z', palier_max_france: 3, palier_max_autour: 2,
        ici: { pft_gw: 213, c_haines: 9.8, palier: 2, potentiel: 'élevé' } },
      { echeance: '2026-07-24T18:00:00Z', palier_max_france: 1, palier_max_autour: 0, ici: null },
    ] }));
    const fixture = creer();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('7,6 GW rayonnés');
    expect(texte).toContain('en baisse');
    expect(texte).toContain('orage au-dessus du feu');
    expect(texte).toContain('le nuage masque peut-être le feu');
    expect(texte).toContain('il en faudrait environ 213 pour un orage de feu ici');
    expect(texte).toContain('Détection satellite, à confirmer');
    expect(fixture.nativeElement.querySelector('.feux svg.courbe path')?.getAttribute('d')).toContain('M0.0');
    // Seule l'heure où le potentiel n'est pas nul autour du territoire est retranscrite.
    expect(fixture.nativeElement.querySelectorAll('.potentiel li').length).toBe(1);
    expect(texte).toContain('un feu d\'environ 213 GW ferait son propre orage sur votre commune');
    expect(service.feuxSuivis).toHaveBeenCalledWith({ rayon_km: 100 });
    discardPeriodicTasks();
  }));

  it('retranscrit les cellules, la plus forte d\'abord, avec le suivi tobac', fakeAsync(() => {
    service.orages.and.returnValue(of(reponse([
      cellule('a', 35),
      cellule('b', 72, { suivi: { suivie_depuis_min: 35, noyaux: 2, noyaux_intenses: 1, surface_10min_km2: 6,
                                   max_10min_mmh: 15, evolution: 'renforcement', fusion: true, division: false } }),
    ])));
    const fixture = creer();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Suivie depuis 35 min');
    expect(texte).toContain('Fusion de cellules');
    const titres = [...fixture.nativeElement.querySelectorAll('app-cellule-orage strong')].map((e: Element) => e.textContent);
    expect(titres[0]).toContain('72 mm/h');
    expect(fixture.componentInstance.synthese).toEqual(jasmine.objectContaining({ cellules: 2, fortes: 1, renforcement: 1 }));
    expect(fixture.debugElement.query(sel => sel.componentInstance instanceof CarteFactice).componentInstance.modeMeteo).toBeTrue();
    discardPeriodicTasks();
  }));

  it('« Voir » fait chercher et mettre en avant la cellule par la carte', fakeAsync(() => {
    service.orages.and.returnValue(of(reponse([cellule('a', 40)])));
    const fixture = creer();
    const carte = fixture.debugElement.query(sel => sel.componentInstance instanceof CarteFactice).componentInstance as CarteFactice;
    // @ViewChild(MapComponent) ne voit pas la carte factice : on la lui donne.
    fixture.componentInstance.carte = carte as unknown as MapComponent;
    (fixture.nativeElement.querySelector('button.voir') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(carte.choix).toEqual([['a', true]]);
    expect(fixture.nativeElement.querySelector('app-cellule-orage.choisie')).not.toBeNull();
    discardPeriodicTasks();
  }));

  it('une cellule cliquée sur la carte est mise en avant dans la liste', fakeAsync(() => {
    service.orages.and.returnValue(of(reponse([cellule('a', 40), cellule('b', 60)])));
    const fixture = creer();
    fixture.componentInstance.surCelluleChoisie('a');
    tick(0);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-cellule-orage.choisie')?.id).toBe('cellule-a');
    fixture.componentInstance.surCelluleChoisie(null);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-cellule-orage.choisie')).toBeNull();
    discardPeriodicTasks();
  }));

  it('sans commune pour l\'institution, montre la France entière', fakeAsync(() => {
    service.orages.and.returnValue(of(reponse([], null)));
    service.oragesFrance.and.returnValue(of(reponse([cellule('a', 40)], null)));
    const fixture = creer();
    expect(fixture.componentInstance.perimetre).toBe('france');
    expect(service.oragesFrance).toHaveBeenCalled();
    expect(service.feuxSuivis).toHaveBeenCalledWith('france');
    expect(fixture.nativeElement.textContent).toContain('Foudre et cumuls de pluie : affichés sur votre territoire seulement');
    discardPeriodicTasks();
  }));
});
