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

  /**
   * Les deux secteurs (13/11/2026). Ce qui est testé ici est la seule chose qui puisse
   * tromper quelqu'un : **la séparation entre ce que je demande et ce que je fais pour les
   * autres**. Les deux viennent du même endpoint (`/dossiers/`), et les confondre montrerait
   * à un bénévole « vos démarches » en parlant des gens qu'il aide.
   */
  describe('les deux secteurs', () => {

    const dossier = (sur: Partial<{ id: string; equipe: string; statut: string }>) => ({
      id: 'd1', numero: 'D-001', crise: 'c1', crise_nom: 'Inondation',
      competence: 'co1', competence_nom: 'Hébergement', titre: 'Besoin de draps',
      description: '', statut: 'EN_COURS', priorite: 'NORMALE' as const, ordre: 0,
      date_creation: '2026-11-01T08:00:00Z', ...sur,
    });

    it('arrive sur la vue d\'ensemble, pas sur un formulaire d\'identité', () => {
      // Personne n'ouvre son espace pour relire son adresse email.
      expect(component.activeTab).toBe('apercu');
    });

    it('sépare mes démarches de mes missions', () => {
      component.mesEquipes = [{ id: 'e1', name: 'Équipe hébergement' } as never];
      component.allDossiers = [
        dossier({ id: 'mien' }),                        // ouvert pour moi : aucune équipe
        dossier({ id: 'mission', equipe: 'e1' }),       // confié à MON équipe
        dossier({ id: 'ailleurs', equipe: 'e9' }),      // une autre équipe : pas ma mission
      ];

      expect(component.mesMissions.map(d => d.id)).toEqual(['mission']);
      expect(component.mesDemarches.map(d => d.id)).toEqual(['mien', 'ailleurs']);
    });

    it('ne compte que ce qui appelle une action', () => {
      // Un compteur qui additionne les dossiers terminés dit « 14 » à quelqu'un qui n'a rien
      // à faire.
      component.mesEquipes = [{ id: 'e1', name: 'Équipe' } as never];
      component.allDossiers = [
        dossier({ id: 'a', equipe: 'e1', statut: 'EN_COURS' }),
        dossier({ id: 'b', equipe: 'e1', statut: 'CLOTURE' }),
        dossier({ id: 'c', equipe: 'e1', statut: 'RESOLU' }),
      ];

      expect(component.missionsEnCours.map(d => d.id)).toEqual(['a']);
      expect(component.missionsPassees.map(d => d.id)).toEqual(['b', 'c']);
    });

    it('sans équipe, tout dossier est une démarche et non une mission', () => {
      component.mesEquipes = [];
      component.allDossiers = [dossier({ id: 'x', equipe: 'e1' })];

      expect(component.mesMissions).toEqual([]);
      expect(component.mesDemarches.length).toBe(1);
    });

    it('reconnaît un vécu de bénévole même sans mission en cours', () => {
      // Faire partie d'une équipe suffit : le secteur doit s'afficher rempli, pas comme si la
      // personne n'avait jamais rien fait.
      component.mesEquipes = [{ id: 'e1', name: 'Équipe' } as never];
      component.allDossiers = [];
      component.allOffers = [];

      expect(component.aUnVecuDeBenevole).toBeTrue();
    });
  });
});
