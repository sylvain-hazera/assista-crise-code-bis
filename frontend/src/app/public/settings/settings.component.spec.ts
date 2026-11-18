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

  /** Demande du 15/11/2026 : nos passerelles entendent des centaines de nœuds, et retrouver le
   * sien dans une liste déroulante de cette taille est pénible. On tape le début du nom. */
  describe('filtre des boîtiers par premières lettres', () => {

    const mc = (nom: string, cle: string) => ({
      pubkey_hex: cle.repeat(32), nom, dernier_advert: null, deja_associe: false, a_moi: false,
    });
    const mt = (num: number, id: string, long: string, court = '') => ({
      node_num: num, node_id: id, long_name: long, short_name: court, hardware_model: 'HELTEC_V3',
      compagnon_id: 'c1', compagnon_nom: 'Pont', dernier_advert: null, deja_associe: false, a_moi: false,
    });

    beforeEach(() => {
      component.candidatsMeshCore = [
        mc('Pilat Graix', 'a1'), mc('Relais du Pilat', 'b2'), mc('Élan 42', 'c3'),
        mc('Talkie de terrain', 'd4'), mc('', 'ab'),
        { ...mc('Pilat réservé', 'e5'), deja_associe: true },
      ];
      component.candidatsMeshtastic = [
        mt(1, '!a1b2c3d4', 'Talkie Jean', 'JEAN'), mt(2, '!ab000001', 'Mairie Saint-Chamond', 'MSC'),
        mt(3, '!0000ab12', '', ''),
      ];
    });

    const noms = () => component.candidatsMeshCoreFiltres.map(c => c.nom);

    it('sans rien taper, toute la liste libre est proposée', () => {
      expect(component.candidatsMeshCoreFiltres.length).toBe(5);
    });

    it('garde les noms qui commencent par les lettres tapées, mot par mot', () => {
      component.filtrerMeshCore('pil');
      // « Relais du Pilat » aussi : les noms portent souvent un préfixe avant le mot cherché.
      expect(noms()).toEqual(['Pilat Graix', 'Relais du Pilat']);
    });

    it('ne trouve pas des lettres situées au milieu d’un mot', () => {
      component.filtrerMeshCore('lat');
      expect(noms()).toEqual([]);
    });

    it('ignore la casse et les accents, dans les deux sens', () => {
      component.filtrerMeshCore('ELAN');
      expect(noms()).toEqual(['Élan 42']);
      component.filtrerMeshCore('élan');
      expect(noms()).toEqual(['Élan 42']);
    });

    it('ne propose jamais un nœud déjà rattaché à quelqu’un, même s’il correspond', () => {
      component.filtrerMeshCore('pilat r');
      expect(noms()).toEqual([]);
    });

    it('ne confond pas les lettres d’un nom avec le début d’une clé', () => {
      // « ab » est aussi le début de la clé du nœud sans nom : lui seul se cherche par sa clé.
      component.filtrerMeshCore('ab');
      expect(component.candidatsMeshCoreFiltres.map(c => c.pubkey_hex.slice(0, 2))).toEqual(['ab']);
      component.filtrerMeshCore('a1');
      expect(component.candidatsMeshCoreFiltres).toEqual([]);
    });

    it('choisit d’office le boîtier quand il n’en reste qu’un', () => {
      component.filtrerMeshCore('talk');
      expect(component.reclamerMeshCorePubkey).toBe('d4'.repeat(32));
    });

    it('défait un choix que le filtre ne montre plus', () => {
      component.reclamerMeshCorePubkey = 'd4'.repeat(32);
      component.filtrerMeshCore('pil');
      expect(component.reclamerMeshCorePubkey).toBe('');
    });

    it('garde le choix tant qu’il reste visible, et ne choisit rien quand le filtre est vide', () => {
      component.reclamerMeshCorePubkey = 'b2'.repeat(32);
      component.filtrerMeshCore('pil');
      expect(component.reclamerMeshCorePubkey).toBe('b2'.repeat(32));
      component.candidatsMeshCore = [mc('Seul', 'a1')];
      component.reclamerMeshCorePubkey = '';
      component.filtrerMeshCore('');
      expect(component.reclamerMeshCorePubkey).toBe('');
    });

    it('côté Meshtastic, cherche dans le nom long comme dans le nom court', () => {
      component.filtrerMeshtastic('saint');
      expect(component.candidatsMeshtasticFiltres.map(c => c.node_num)).toEqual([2]);
      component.filtrerMeshtastic('jea');
      expect(component.candidatsMeshtasticFiltres.map(c => c.node_num)).toEqual([1]);
      expect(component.reclamerMeshtasticNodeNum).toBe(1);
    });

    it('côté Meshtastic, « ! » cherche l’identifiant et rien d’autre', () => {
      component.filtrerMeshtastic('!ab');
      expect(component.candidatsMeshtasticFiltres.map(c => c.node_num)).toEqual([2]);
      // Sans « ! », « ab » ne ramène pas les identifiants : seulement le nœud sans nom, qui
      // n'a que son identifiant pour être reconnu... et il commence par 0000.
      component.filtrerMeshtastic('ab');
      expect(component.candidatsMeshtasticFiltres).toEqual([]);
      component.filtrerMeshtastic('0000');
      expect(component.candidatsMeshtasticFiltres.map(c => c.node_num)).toEqual([3]);
    });
  });

  /**
   * Les deux secteurs (13/11/2026). Ce qui est testé ici est la seule chose qui puisse
   * tromper quelqu'un : **la séparation entre ce que je demande et ce que je fais pour les
   * autres**. Les deux viennent du même endpoint (`/dossiers/`), et les confondre montrerait
   * à un bénévole « vos démarches » en parlant des gens qu'il aide.
   */
  describe('les deux secteurs', () => {

    const dossier = (sur: Partial<{ id: string; equipe: string; statut: string; demande: string; information: string }>) => ({
      id: 'd1', numero: 'D-001', crise: 'c1', crise_nom: 'Inondation',
      competence: 'co1', competence_nom: 'Hébergement', titre: 'Besoin de draps',
      description: '', statut: 'EN_COURS', priorite: 'NORMALE' as const, ordre: 0,
      date_creation: '2026-11-01T08:00:00Z', ...sur,
    });

    it('arrive sur la vue d\'ensemble, pas sur un formulaire d\'identité', () => {
      // Personne n'ouvre son espace pour relire son adresse email.
      expect(component.activeTab).toBe('apercu');
    });

    it('mes démarches sont celles dont je suis à l\'initiative, pas ce que mon compte peut voir', () => {
      // 18/11/2026 : un agent de mairie y lisait les 289 dossiers visibles de son compte.
      component.mesEquipes = [{ id: 'e1', name: 'Équipe hébergement' } as never];
      component.allRequests = [{ id: 'd1' } as never];
      component.allInformations = [{ id: 's1' } as never];
      component.allDossiers = [
        dossier({ id: 'ma-demande', demande: 'd1' }),
        dossier({ id: 'mon-signalement', information: 's1' }),
        dossier({ id: 'mission', equipe: 'e1', demande: 'autre' }),   // confié à MON équipe
        dossier({ id: 'visible', demande: 'autre' }),                 // visible, pas à moi
        dossier({ id: 'generique' }),                                 // ni demande ni signalement
      ];

      expect(component.mesMissions.map(d => d.id)).toEqual(['mission']);
      expect(component.mesDemarches.map(d => d.id)).toEqual(['ma-demande', 'mon-signalement']);
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

    it('sans équipe, aucun dossier n\'est une mission', () => {
      component.mesEquipes = [];
      component.allDossiers = [dossier({ id: 'x', equipe: 'e1' })];

      expect(component.mesMissions).toEqual([]);
      expect(component.mesDemarches).toEqual([]);
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

  /**
   * Le repliement par groupe (13/11/2026). Sur smartphone, un seul groupe est déplié : dix
   * onglets empilés feraient six cents pixels de navigation avant le premier contenu. Ce qui
   * compte est qu'on ne puisse jamais se retrouver avec l'onglet actif dans un groupe fermé —
   * il serait alors invisible dans la barre, sans rien pour le retrouver.
   */
  describe('le groupe déplié', () => {

    it('suit l\'onglet choisi', () => {
      component.setActiveTab('dossier');
      expect(component.groupeOuvert).toBe('aide');

      component.setActiveTab('radio');
      expect(component.groupeOuvert).toBe('benevole');

      component.setActiveTab('password');
      expect(component.groupeOuvert).toBe('compte');
    });

    it('ne change rien pour la vue d\'ensemble, qui n\'appartient à aucun groupe', () => {
      component.setActiveTab('radio');
      component.setActiveTab('apercu');
      // Le groupe reste tel quel : refermer tout laisserait la barre sans repère au retour.
      expect(component.groupeOuvert).toBe('benevole');
    });

    it('un en-tête de groupe ouvre, il ne referme pas', () => {
      // Replier le groupe courant ferait disparaître l'onglet actif sans rien mettre à la
      // place.
      component.ouvrirGroupe('compte');
      component.ouvrirGroupe('compte');
      expect(component.groupeOuvert).toBe('compte');
    });
  });
});
