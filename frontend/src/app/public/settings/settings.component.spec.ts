import { ComponentFixture, TestBed } from '@angular/core/testing';

import { SettingsComponent } from './settings.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('SettingsComponent', () => {
  let component: SettingsComponent;
  let fixture: ComponentFixture<SettingsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [SettingsComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(SettingsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  /** Le choix dans une liste remplace la recopie de 64 caracteres hexadecimaux a la main, qui
   * etait la seule facon de se rattacher jusqu'au 11/11/2026 -- et une faute de frappe
   * rattache un noeud qui n'est pas le sien. */
  describe('choix d\'un noeud entendu', () => {

    const CANDIDAT_MC = {
      pubkey_hex: 'a1'.repeat(32), nom: 'Talkie de terrain',
      dernier_advert: '2026-11-11T08:00:00Z', deja_associe: false, a_moi: false,
    };

    it('ne propose pas au choix un noeud deja rattache a quelqu\'un', () => {
      component.candidatsMeshCore = [
        CANDIDAT_MC,
        { ...CANDIDAT_MC, pubkey_hex: 'b2'.repeat(32), deja_associe: true },
      ];
      // Il reste AFFICHE en compte dans l'explication, mais il n'est pas selectionnable :
      // le reclamer echouerait de toute facon cote serveur.
      expect(component.candidatsMeshCoreLibres.length).toBe(1);
      expect(component.candidatsMeshCoreLibres[0].pubkey_hex).toBe('a1'.repeat(32));
    });

    it('remplit la cle ET le nom annonce par l\'appareil', () => {
      component.reclamerMeshCorePubkey = '';
      component.reclamerMeshCoreNom = '';
      component.choisirCandidatMeshCore(CANDIDAT_MC);
      expect(component.reclamerMeshCorePubkey).toBe('a1'.repeat(32));
      expect(component.reclamerMeshCoreNom).toBe('Talkie de terrain');
    });

    it('ne remplace pas un nom que l\'utilisateur a deja saisi', () => {
      component.reclamerMeshCoreNom = 'Mon boitier a moi';
      component.choisirCandidatMeshCore(CANDIDAT_MC);
      expect(component.reclamerMeshCoreNom).toBe('Mon boitier a moi');
    });

    it('cote Meshtastic, retient le node_num entier et non l\'identifiant affiche', () => {
      component.reclamerMeshtasticNom = '';
      component.choisirCandidatMeshtastic({
        node_num: 0xa1b2c3d4, node_id: '!a1b2c3d4', long_name: 'Talkie Jean',
        short_name: 'JEAN', hardware_model: 'HELTEC_V3', compagnon_id: 'c1',
        compagnon_nom: 'Pont Gaulix', dernier_advert: null, deja_associe: false, a_moi: false,
      });
      // L'API attend l'entier ; c'est l'affichage qui montre `!a1b2c3d4`, la forme que
      // l'appareil lui-meme donne.
      expect(component.reclamerMeshtasticNodeNum).toBe(0xa1b2c3d4);
      expect(component.reclamerMeshtasticNom).toBe('Talkie Jean');
    });
  });
});
