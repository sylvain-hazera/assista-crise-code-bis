import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';
import { AuthService } from '../auth/services/auth.service';
import { UserRole } from '../shared/models/user.model';
import { HorsLigneService } from './hors-ligne.service';
import { DegatsService } from './degats/degats.service';
import { SuiviTerrainService } from './position/suivi-terrain.service';
import { evalueLesDegats } from './droits';
import {
  ETAT_INITIAL, EtatSuivi, INTERVALLE_IMMOBILE_MS, PLAFOND_MS, Releve, doitDemarrer, doitEnvoyer, engagementCourant, motifArret,
} from './position/regles-suivi';
import { Constat, SecteurEmbarque, prochainPoint, secteurAEffacer, tourneeHorsLigne } from './degats/degats';
import { dimensionsReduites, empreinte, insererExif, segmentExif } from './photo/photo-scellee';

const api = environment.apiUrl;
const attendre = (ms = 30) => new Promise(r => setTimeout(r, ms));
const releve = (latitude: number, longitude: number, instant: number): Releve => ({ latitude, longitude, instant, precision_m: 5 });

describe('Terrain, lot 5 : règles du suivi de position (comme Android)', () => {
  const engagee = [{ engagement_debut: '2026-11-21T08:00:00Z' }, { engagement_debut: null }];

  it('ne démarre jamais sans accord, ni hors engagement, ni pour un engagement arrêté à la main', () => {
    expect(doitDemarrer(ETAT_INITIAL, engagee)).toBeFalse();
    const accord: EtatSuivi = { ...ETAT_INITIAL, consentement: true };
    expect(doitDemarrer(accord, [{ engagement_debut: null }])).toBeFalse();
    expect(doitDemarrer(accord, engagee)).toBeTrue();
    expect(doitDemarrer({ ...accord, engagement_arrete: '2026-11-21T08:00:00Z' }, engagee)).toBeFalse();
    expect(engagementCourant([{ engagement_debut: '2026-11-21T09:00:00Z' }, { engagement_debut: '2026-11-21T08:00:00Z' }]))
      .toBe('2026-11-21T08:00:00Z');
  });

  it('s\'arrête au plafond de douze heures, ou à la fin de l\'engagement ; pas sur une absence de nouvelles', () => {
    const actif: EtatSuivi = { ...ETAT_INITIAL, consentement: true, depuis: 0 };
    expect(motifArret(actif, null, PLAFOND_MS - 1)).toBeNull();
    expect(motifArret(actif, null, PLAFOND_MS)).toBe('PLAFOND');
    expect(motifArret(actif, [{ engagement_debut: null }], 1000)).toBe('FIN_D_ENGAGEMENT');
    expect(motifArret(actif, engagee, 1000)).toBeNull();
  });

  it('cadence : pas plus d\'une position par 30 s ; à l\'arrêt, une toutes les 5 min', () => {
    const a = releve(45, 1, 0);
    expect(doitEnvoyer(null, a)).toBeTrue();
    expect(doitEnvoyer(a, releve(45.001, 1, 20_000))).toBeFalse();          // a bougé, mais trop tôt
    expect(doitEnvoyer(a, releve(45.001, 1, 40_000))).toBeTrue();           // ~111 m
    expect(doitEnvoyer(a, releve(45.00001, 1, 40_000))).toBeFalse();        // ~1 m : bruit du GPS
    expect(doitEnvoyer(a, releve(45.00001, 1, INTERVALLE_IMMOBILE_MS))).toBeTrue();
  });
});

describe('Terrain, lot 5 : la tournée des dégâts hors réseau', () => {
  const secteur: SecteurEmbarque = {
    crise: 'c', latitude: 45, longitude: 1, rayon_m: 1000, genere_le: '2026-11-21T08:00:00Z',
    adresses: [['ban-1', '1 rue des Pins', 45.0001, 1], ['ban-2', '3 rue des Pins', 45.0005, 1], ['ban-loin', 'Loin', 45.01, 1]],
    biens: [
      { id: 'h1', ban_id: 'ban-2', adresse: '3 rue des Pins', latitude: 45.0004, longitude: 1, statut_evaluation: 'DEGATS_FORTS',
        type_bien: 'Logement', position_corrigee: true },
      { id: 'h2', ban_id: null, adresse: 'Voiture — parking', latitude: 45.0002, longitude: 1, statut_evaluation: 'NON_EVALUEE',
        type_bien: 'Véhicule', position_corrigee: false },
    ],
    dossiers: [], cercles: [],
  };
  const constat = (champs: Partial<Constat>): Constat => ({
    id: 'k', crise: 'c', position_corrigee: false, statut_evaluation: 'DEGATS_FAIBLES', dangers: [], personne_sur_place: null,
    a_reloger: null, ouvrir_dossier: false, constate_le: '2026-11-21T09:00:00Z', ...champs,
  });

  it('adresses, biens sans adresse et points ajoutés ici, du plus proche au plus lointain, dans le rayon', () => {
    const points = tourneeHorsLigne(secteur, [constat({ ban_id: 'ban-1' }),
      constat({ latitude: 45.0003, longitude: 1, description: 'Arbre sur la route' })], 45, 1);
    expect(points.map(p => p.libelle)).toEqual(['1 rue des Pins', 'Voiture — parking', 'Arbre sur la route', '3 rue des Pins']);
    expect(points[0].en_attente).toBeTrue();
    const pins3 = points.find(p => p.ban_id === 'ban-2')!;
    expect(pins3.habitation).toBe('h1');
    expect(pins3.latitude).toBe(45.0004);                                   // la position replacée du bien
    expect(points.some(p => p.ban_id === 'ban-loin')).toBeFalse();
    expect(prochainPoint(points)!.libelle).toBe('Voiture — parking');
    expect(prochainPoint(points, 'h2')).toBeNull();
  });

  it('le secteur s\'efface quand ce qui y a été saisi est parti', () => {
    expect(secteurAEffacer(secteur, [])).toBeFalse();                       // rien saisi
    expect(secteurAEffacer({ ...secteur, constats_faits: 1 }, ['constat'])).toBeFalse();
    expect(secteurAEffacer({ ...secteur, constats_faits: 1 }, ['photo_constat'])).toBeFalse();
    expect(secteurAEffacer({ ...secteur, constats_faits: 1 }, ['statut_mission'])).toBeTrue();
  });
});

describe('Terrain, lot 5 : la photo scellée', () => {
  it('écrit un bloc EXIF lisible : en-tête, IFD petit-boutiste, position et heure GPS', () => {
    const segment = segmentExif(Date.UTC(2026, 10, 21, 14, 3, 9), 'Essai',
                                { latitude: -21.1, longitude: 55.5, instant: Date.UTC(2026, 10, 21, 14, 3, 5), precision_m: 12.5 });
    const vue = new DataView(segment.buffer);
    expect(vue.getUint16(0)).toBe(0xffe1);
    expect(vue.getUint16(2)).toBe(segment.length - 2);
    expect(new TextDecoder().decode(segment.subarray(4, 8))).toBe('Exif');
    expect(new TextDecoder().decode(segment.subarray(10, 12))).toBe('II');
    const texte = new TextDecoder('latin1').decode(segment);
    expect(texte).toContain('Essai');
    expect(texte).toContain('2026:11:21');
    expect(texte).toMatch(/S\0/);                                           // latitude sud (La Réunion)
    expect(texte).toMatch(/E\0/);
  });

  it('insère l\'EXIF après l\'en-tête JFIF et remplace un ancien bloc', () => {
    const jfif = [0xff, 0xe0, 0x00, 0x04, 0x4a, 0x46];
    const ancien = [0xff, 0xe1, 0x00, 0x08, 0x45, 0x78, 0x69, 0x66, 0, 0];
    const jpeg = new Uint8Array([0xff, 0xd8, ...jfif, ...ancien, 0xff, 0xdb, 0x00, 0x02, 0xff, 0xd9]);
    const segment = new Uint8Array([0xff, 0xe1, 0x00, 0x03, 0x99]);
    const sortie = Array.from(insererExif(jpeg, segment));
    expect(sortie).toEqual([0xff, 0xd8, ...jfif, 0xff, 0xe1, 0x00, 0x03, 0x99, 0xff, 0xdb, 0x00, 0x02, 0xff, 0xd9]);
    expect(() => insererExif(new Uint8Array([1, 2, 3]), segment)).toThrow();
  });

  it('réduit à 2048 px au plus, sans jamais agrandir, et scelle par SHA-256', async () => {
    expect(dimensionsReduites(4032, 3024)).toEqual([2048, 1536]);
    expect(dimensionsReduites(3024, 4032)).toEqual([1536, 2048]);
    expect(dimensionsReduites(800, 600)).toEqual([800, 600]);
    const abc = new Uint8Array(new ArrayBuffer(3));
    abc.set([0x61, 0x62, 0x63]);
    expect(await empreinte(abc)).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });

  it('le décodeur de QR intégré (pour Safari) est servi par le site', async () => {
    const jsQR = (await import('jsqr')).default;
    const blanc = new Uint8ClampedArray(40 * 40 * 4).fill(255);
    expect(jsQR(blanc, 40, 40)).toBeNull();
  });
});

describe('Terrain, lot 5 : file, photos, dégâts et partage de position', () => {
  let http: HttpTestingController;
  let horsLigne: HorsLigneService;

  beforeEach(async () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    horsLigne = TestBed.inject(HorsLigneService);
    await horsLigne.effacer();
  });
  afterEach(async () => { await horsLigne.effacer(); });

  it('une photo de dossier part en formulaire ; une empreinte différente est signalée, et les octets effacés', async () => {
    const octets = new Uint8Array([0xff, 0xd8, 0xff, 0xd9]);
    const cle = await horsLigne.garderPhoto(octets);
    expect(await horsLigne.lirePhoto(cle)).toEqual(octets);
    await horsLigne.differer({ genre: 'photo_dossier', dossier: 'd1', cle, empreinte: 'aaa', commentaire: '', libelle: 'Photo — Cave',
                               faite_le: '' });
    const envoi = horsLigne.envoyer();
    await attendre(100);
    const requete = http.expectOne(`${api}/documents/`);
    const formulaire = requete.request.body as FormData;
    expect(formulaire.get('dossier')).toBe('d1');
    expect((formulaire.get('fichier') as File).size).toBe(4);
    requete.flush({ id: 'p', sha256: 'bbb' });
    expect(await envoi).toBe(1);
    expect(horsLigne.refus()[0].libelle).toBe('Photo — Cave');
    expect(horsLigne.refus()[0].motif).toContain('empreinte');
    expect(await horsLigne.lirePhoto(cle)).toBeNull();
    expect(horsLigne.enAttente()).toBe(0);
  });

  it('sans réseau, une seule position attend : la dernière', async () => {
    await horsLigne.remplacer({ genre: 'position', latitude: 1, longitude: 1, faite_le: '' });
    await horsLigne.remplacer({ genre: 'position', latitude: 2, longitude: 2, faite_le: '' });
    const file = await horsLigne.enFile();
    expect(file.length).toBe(1);
    expect(file[0].valeur).toEqual(jasmine.objectContaining({ latitude: 2 }));
  });

  it('un constat part avec son identifiant ; sans réseau, la tournée vient du secteur embarqué', async () => {
    const degats = TestBed.inject(DegatsService);
    await degats.restaurer();
    const ici = releve(45, 1, Date.now());

    const embarque = degats.embarquer('c', ici);
    http.expectOne(r => r.url === `${api}/types-bien/`).flush([]);
    const secteur = http.expectOne(r => r.url === `${api}/habitations/secteur/`);
    expect(secteur.request.params.get('rayon_m')).toBe('1000');
    secteur.flush({ crise: 'c', latitude: 45, longitude: 1, rayon_m: 1000, genere_le: '2026-11-21T08:00:00Z',
                    adresses: [['ban-1', '1 rue des Pins', 45.0001, 1]], biens: [], dossiers: [], cercles: [] });
    expect(await embarque).toContain('1 adresses');

    const tournee = degats.tournee('c', ici);
    await attendre(100);
    http.expectOne(r => r.url === `${api}/habitations/tournee/`).error(new ProgressEvent('error'));
    const t = await tournee;
    expect(t.horsLigne).toBeTrue();
    expect(t.points.map(p => p.libelle)).toEqual(['1 rue des Pins']);

    const constat: Constat = { id: '3b0c8f9e-0000-4000-8000-000000000001', crise: 'c', ban_id: 'ban-1', position_corrigee: false,
      statut_evaluation: 'DEGATS_FORTS', dangers: ['GAZ'], personne_sur_place: false, a_reloger: false, ouvrir_dossier: false,
      constate_le: '2026-11-21T09:00:00Z' };
    const fait = degats.constater(constat, 'Évaluation : 1 rue des Pins', [], ici);
    await attendre(150);
    const post = http.expectOne(`${api}/habitations/constat/`);
    expect(post.request.body.id).toBe(constat.id);
    expect(post.request.body.dangers).toEqual(['GAZ']);
    post.flush({ constat: constat.id });
    expect(await fait).toBe(0);
    await attendre();
    expect(degats.secteur()).toBeNull();                                    // tout est parti : le secteur s'efface
  });

  it('le partage de position ne démarre qu\'avec l\'accord, pendant un engagement, et envoie ma position', async () => {
    const suivi = TestBed.inject(SuiviTerrainService);
    let surPosition: PositionCallback | null = null;
    const surveiller = spyOn(navigator.geolocation, 'watchPosition').and.callFake((cb: PositionCallback) => { surPosition = cb; return 7; });
    spyOn(navigator.geolocation, 'clearWatch');
    await suivi.toutEffacer();

    const debut = suivi.demarrer();
    await attendre();
    http.expectOne(`${api}/teams/mes-equipes/`).flush([{ engagement_debut: '2026-11-21T08:00:00Z' }]);
    await debut;
    expect(suivi.engagementEnCours()).toBeTrue();
    expect(surveiller).not.toHaveBeenCalled();                              // pas d'accord : rien

    const accord = suivi.consentir();
    await attendre();
    http.expectOne(`${api}/teams/mes-equipes/`).flush([{ engagement_debut: '2026-11-21T08:00:00Z' }]);
    await accord;
    expect(suivi.actif()).toBeTrue();
    expect(surveiller).toHaveBeenCalled();

    surPosition!({ coords: { latitude: 45.1, longitude: 1.2, accuracy: 8 }, timestamp: Date.now() } as GeolocationPosition);
    await attendre(100);
    const position = http.expectOne(`${api}/ma-position/`);
    expect(position.request.body).toEqual({ latitude: 45.1, longitude: 1.2 });
    position.flush({});

    await suivi.arreterALaMainMaintenant();
    expect(suivi.actif()).toBeFalse();
    expect(suivi.arreteALaMain()).toBeTrue();
    await suivi.toutEffacer();
  });

  it('l\'évaluation des dégâts est réservée au personnel municipal, aux élus et à l\'administrateur', () => {
    const auth = TestBed.inject(AuthService);
    const role = spyOn(auth, 'getEffectiveRole');
    role.and.returnValue(UserRole.LOCAL_AUTH);
    expect(evalueLesDegats(auth)).toBeTrue();
    role.and.returnValue(UserRole.ADMIN);
    expect(evalueLesDegats(auth)).toBeTrue();
    role.and.returnValue(UserRole.RESCUE);
    expect(evalueLesDegats(auth)).toBeFalse();
    role.and.returnValue(UserRole.SIMPLE_USER);
    expect(evalueLesDegats(auth)).toBeFalse();
  });
});
