import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MeshtasticAdministrationComponent } from './meshtastic-administration.component';
import { environment } from '../../../environments/environment';
import { CompagnonMeshtastic } from '../../shared/models/compagnon-meshtastic.model';
import {
  ConfigurationNoeudMeshtastic, TacheAdminMeshtastic,
} from '../../shared/models/administration-meshtastic.model';

function compagnon(partiel: Partial<CompagnonMeshtastic>): CompagnonMeshtastic {
  return {
    id: 'p1', nom: 'Passerelle mairie', connexion_type: 'SERIE', node_num: 0x1a2b3c4d,
    broker_host: '', broker_port: 1883, topic_racine: 'msh/EU_868', mqtt_use_tls: false,
    principal: false, actif: true, chiffrement_supporte: false,
    ...partiel,
  } as CompagnonMeshtastic;
}

const UNE_TACHE: TacheAdminMeshtastic = {
  id: 't1', compagnon: 'p1', compagnon_nom: 'Passerelle mairie', node_num_cible: null,
  type_tache: 'LIRE_CONFIG_LORA', type_tache_libelle: 'Lire la configuration LoRa',
  statut: 'TERMINEE', tentatives: 1, reponse: '{"puissance_emission_dbm": 22}',
  date_creation: '2026-11-06T10:00:00Z',
};

describe('MeshtasticAdministrationComponent', () => {
  let http: HttpTestingController;
  const urlTaches = `${environment.apiUrl}/taches-admin-meshtastic`;
  const urlCompagnons = `${environment.apiUrl}/compagnons-meshtastic`;
  const urlConfigs = `${environment.apiUrl}/configurations-noeuds-meshtastic`;
  const urlContacts = `${environment.apiUrl}/contacts-meshtastic`;
  const urlReglages = `${urlTaches}/reglages/`;

  /** Catalogue minimal, dans la forme exacte que sert le serveur. */
  const CATALOGUE = {
    lora: {
      libelle: 'Radio LoRa', module: false, redemarre: true,
      champs: {
        hop_limit: { type: 'entier', libelle: 'Nombre de sauts', aide: 'x', mini: 1, maxi: 7,
                     valeurs_speciales: [] },
        region: { type: 'enumeration', libelle: 'Région', aide: 'x', valeurs: ['EU_868', 'EU_433'] },
        tx_enabled: { type: 'booleen', libelle: 'Émission activée', aide: 'x' },
      },
    },
    voisinage: {
      libelle: 'Module Voisinage', module: true, redemarre: false,
      champs: {
        enabled: { type: 'booleen', libelle: 'Module activé', aide: 'x' },
        update_interval: { type: 'entier', libelle: 'Intervalle', aide: 'x',
                           mini: 14400, maxi: 604800, valeurs_speciales: [] },
      },
    },
  } as any;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MeshtasticAdministrationComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  /** Répond aux quatre appels de démarrage. `passerelles` permet de simuler un parc sans
   * appareil réel (cas où la page doit refuser d'agir). */
  function demarrer(passerelles: CompagnonMeshtastic[] = [compagnon({})]) {
    const fixture = TestBed.createComponent(MeshtasticAdministrationComponent);
    fixture.detectChanges();
    http.expectOne(`${urlCompagnons}/`).flush(passerelles);
    if (passerelles.some((p) => p.connexion_type !== 'MQTT')) {
      http.expectOne((r) => r.url === `${urlContacts}/`).flush([]);
    }
    http.expectOne(`${urlTaches}/`).flush([UNE_TACHE]);
    http.expectOne(`${urlConfigs}/`).flush([]);
    http.expectOne(urlReglages).flush(CATALOGUE);
    return fixture.componentInstance;
  }

  it('ne retient comme passerelles que les companions reliés à un vrai appareil', () => {
    // Un companion MQTT n'a pas d'appareil : c'est le firmware de l'appareil qui chiffre le
    // message d'administration, donc MQTT ne peut rien administrer.
    const composant = demarrer([
      compagnon({ id: 'p1', connexion_type: 'SERIE' }),
      compagnon({ id: 'p2', connexion_type: 'MQTT', nom: 'Gaulix' }),
      compagnon({ id: 'p3', connexion_type: 'TCP', nom: 'Appareil WiFi' }),
    ]);
    expect(composant.passerelles.map((p) => p.id)).toEqual(['p1', 'p3']);
    expect(composant.nouvelle.compagnon).toBe('p1');
  });

  it('vise la passerelle elle-même par défaut : le seul cas sans autorisation préalable', () => {
    const composant = demarrer();
    expect(composant.nouvelle.cible).toBe('');
    expect(composant.viseUnNoeudDistant).toBeFalse();

    composant.envoyer();
    const envoi = http.expectOne(`${urlTaches}/`);
    expect(envoi.request.body.node_num_cible).toBeNull();
    envoi.flush(UNE_TACHE);
    http.expectOne(`${urlTaches}/`).flush([UNE_TACHE]);
    http.expectOne(`${urlConfigs}/`).flush([]);
  });

  it('demande confirmation avant une écriture, et n’envoie rien avant', () => {
    const composant = demarrer();
    composant.nouvelle.type_tache = 'DEFINIR_PUISSANCE';
    composant.nouvelle.puissance_dbm = 20;

    composant.demanderConfirmation();
    expect(composant.confirmationDemandee).toBeTrue();
    http.expectNone(`${urlTaches}/`);

    composant.envoyer();
    const envoi = http.expectOne(`${urlTaches}/`);
    expect(envoi.request.body.parametres).toEqual({ puissance_dbm: 20 });
    expect(composant.confirmationDemandee).toBeFalse();
    envoi.flush(UNE_TACHE);
    http.expectOne(`${urlTaches}/`).flush([UNE_TACHE]);
    http.expectOne(`${urlConfigs}/`).flush([]);
  });

  it('envoie directement une lecture, sans confirmation', () => {
    const composant = demarrer();
    composant.nouvelle.type_tache = 'LIRE_METADATA';
    composant.demanderConfirmation();
    expect(composant.confirmationDemandee).toBeFalse();
    http.expectOne(`${urlTaches}/`).flush(UNE_TACHE);
    http.expectOne(`${urlTaches}/`).flush([UNE_TACHE]);
    http.expectOne(`${urlConfigs}/`).flush([]);
  });

  it('remonte le motif exact d’un refus du serveur', () => {
    const composant = demarrer();
    composant.envoyer();
    http.expectOne(`${urlTaches}/`).flush(
      { detail: "Écrire sur un nœud radio est réservé aux administrateurs." },
      { status: 403, statusText: 'Forbidden' },
    );
    expect(composant.erreurEnvoi).toContain('administrateurs');
    expect(composant.envoiEnCours).toBeFalse();
  });

  it('n’affiche jamais « 0 dBm » : le firmware applique alors le maximum de la région', () => {
    // Piège central de tout ce dispositif : tx_power = 0 n'est pas une puissance nulle, c'est
    // une puissance INCONNUE. L'afficher « 0 dBm » tromperait sur la foi à y mettre, et
    // core/analyse_liaisons.py la traite d'ailleurs comme absente.
    const composant = demarrer();
    const base: ConfigurationNoeudMeshtastic = {
      id: 'c1', node_num: 1, puissance_emission_dbm: 0, region: 'EU_868',
      modem_preset: 'LONG_FAST', hop_limit: 3, role: 'ROUTER', firmware_version: '2.7.4',
      hardware_model: 'HELTEC_V3', date_releve: '2026-11-06T10:00:00Z',
    };
    expect(composant.puissanceLisible(base)).toContain('inconnue');
    expect(composant.puissanceLisible(base)).not.toContain('0 dBm');
    expect(composant.puissanceLisible({ ...base, puissance_emission_dbm: null })).toBe('inconnue');
    expect(composant.puissanceLisible({ ...base, puissance_emission_dbm: 22 })).toBe('22 dBm');
  });

  it('met en forme la réponse JSON du pont et désigne clairement la passerelle', () => {
    const composant = demarrer();
    expect(composant.reponseLisible(UNE_TACHE)).toContain('puissance_emission_dbm');
    expect(composant.nomNoeud(null)).toContain('passerelle');
    expect(composant.hexa(0x1a2b3c4d)).toBe('!1a2b3c4d');
  });

  it('dit quoi faire quand aucune passerelle ne peut administrer', () => {
    const composant = demarrer([compagnon({ connexion_type: 'MQTT' })]);
    expect(composant.passerelles.length).toBe(0);
    expect(composant.nouvelle.compagnon).toBe('');
  });
});

describe('MeshtasticAdministrationComponent — éditeur de réglages', () => {
  let http: HttpTestingController;
  const urlTaches = `${environment.apiUrl}/taches-admin-meshtastic`;
  const urlReglages = `${urlTaches}/reglages/`;

  const CATALOGUE = {
    lora: {
      libelle: 'Radio LoRa', module: false, redemarre: true,
      champs: {
        hop_limit: { type: 'entier', libelle: 'Nombre de sauts', aide: 'x', mini: 1, maxi: 7,
                     valeurs_speciales: [] },
        region: { type: 'enumeration', libelle: 'Région', aide: 'x', valeurs: ['EU_868', 'EU_433'] },
        tx_enabled: { type: 'booleen', libelle: 'Émission activée', aide: 'x' },
      },
    },
    voisinage: {
      libelle: 'Module Voisinage', module: true, redemarre: false,
      champs: {
        enabled: { type: 'booleen', libelle: 'Module activé', aide: 'x' },
        update_interval: { type: 'entier', libelle: 'Intervalle', aide: 'x',
                           mini: 14400, maxi: 604800, valeurs_speciales: [] },
      },
    },
  } as any;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MeshtasticAdministrationComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer() {
    const fixture = TestBed.createComponent(MeshtasticAdministrationComponent);
    fixture.detectChanges();
    http.expectOne(`${environment.apiUrl}/compagnons-meshtastic/`).flush([{
      id: 'p1', nom: 'Passerelle', connexion_type: 'SERIE', node_num: 1,
      broker_host: '', broker_port: 1883, topic_racine: 'x', mqtt_use_tls: false,
      principal: false, actif: true, chiffrement_supporte: false,
    }]);
    http.expectOne(r => r.url === `${environment.apiUrl}/contacts-meshtastic/`).flush([]);
    http.expectOne(`${urlTaches}/`).flush([]);
    http.expectOne(`${environment.apiUrl}/configurations-noeuds-meshtastic/`).flush([]);
    http.expectOne(urlReglages).flush(CATALOGUE);
    return fixture;
  }

  it('n’envoie QUE les réglages cochés', () => {
    // LE point de correction : le firmware remplace tout le bloc, et le pont relit puis renvoie
    // les champs non cochés inchangés. Envoyer un champ non coché l'écraserait par la valeur
    // affichée dans le formulaire — sur la section LoRa, cela effacerait la région.
    const composant = demarrer().componentInstance;
    composant.nouvelle.type_tache = 'DEFINIR_REGLAGES';
    composant.sectionChoisie = 'lora';
    composant.reinitialiserReglages();
    composant.reglagesModifies['hop_limit'] = { actif: true, valeur: 5 };

    composant.envoyer();
    const requete = http.expectOne(`${urlTaches}/`);
    expect(requete.request.body.parametres).toEqual({ section: 'lora', valeurs: { hop_limit: 5 } });
    requete.flush({});
    http.expectOne(`${urlTaches}/`).flush([]);
    http.expectOne(`${environment.apiUrl}/configurations-noeuds-meshtastic/`).flush([]);
  });

  it('refuse d’envoyer quand rien n’est coché', () => {
    const composant = demarrer().componentInstance;
    composant.nouvelle.type_tache = 'DEFINIR_REGLAGES';
    composant.reinitialiserReglages();
    expect(composant.aucunReglageCoche).toBeTrue();
  });

  it('changer de section n’emporte pas les coches de la précédente', () => {
    const composant = demarrer().componentInstance;
    composant.sectionChoisie = 'lora';
    composant.reinitialiserReglages();
    composant.reglagesModifies['hop_limit'].actif = true;

    composant.sectionChoisie = 'voisinage';
    composant.reinitialiserReglages();
    expect(composant.aucunReglageCoche).toBeTrue();
    expect(Object.keys(composant.reglagesModifies).sort()).toEqual(['enabled', 'update_interval']);
  });

  it('propose les bornes du serveur, jamais recopiées ici', () => {
    // 4 h pour le voisinage : contrainte du firmware. Si elle était dupliquée dans le frontend,
    // elle divergerait au premier changement côté serveur.
    const composant = demarrer().componentInstance;
    composant.sectionChoisie = 'voisinage';
    const champ = composant.champsSection.find(c => c.cle === 'update_interval');
    expect(champ?.champ.mini).toBe(14400);
  });

  it('annonce que la section LoRa fait redémarrer le nœud', () => {
    const composant = demarrer().componentInstance;
    composant.sectionChoisie = 'lora';
    expect(composant.sectionCourante?.redemarre).toBeTrue();
    composant.sectionChoisie = 'voisinage';
    expect(composant.sectionCourante?.redemarre).toBeFalse();
  });

  it('une lecture de section n’envoie que la section', () => {
    const composant = demarrer().componentInstance;
    composant.nouvelle.type_tache = 'LIRE_REGLAGES';
    composant.sectionChoisie = 'voisinage';
    composant.envoyer();
    const requete = http.expectOne(`${urlTaches}/`);
    expect(requete.request.body.parametres).toEqual({ section: 'voisinage' });
    requete.flush({});
    http.expectOne(`${urlTaches}/`).flush([]);
    http.expectOne(`${environment.apiUrl}/configurations-noeuds-meshtastic/`).flush([]);
  });

  it('compte le nom court en OCTETS, pas en caractères', () => {
    // Quatre lettres accentuées font huit octets : le firmware tronquerait en silence.
    const composant = demarrer().componentInstance;
    expect(composant.octets('PILA')).toBe(4);
    expect(composant.octets('éééé')).toBe(8);
    // Un émoji simple fait exactement 4 octets : il consomme TOUT le budget du nom court.
    expect(composant.octets('🛰')).toBe(4);
    // Avec son sélecteur de variation, il le dépasse.
    expect(composant.octets('🛰️')).toBeGreaterThan(4);
  });

  it('n’envoie pas un nom vide', () => {
    const composant = demarrer().componentInstance;
    composant.nouvelle.type_tache = 'DEFINIR_NOM';
    composant.nom = { nom_long: '  ', nom_court: '' };
    composant.envoyer();
    const requete = http.expectOne(`${urlTaches}/`);
    expect(requete.request.body.parametres).toEqual({});
    requete.flush(null, { status: 400, statusText: 'Bad Request' });
  });

  it('reste utilisable si le catalogue ne répond pas', () => {
    // Les lectures et les autres opérations ne dépendent pas du catalogue.
    const fixture = TestBed.createComponent(MeshtasticAdministrationComponent);
    fixture.detectChanges();
    http.expectOne(`${environment.apiUrl}/compagnons-meshtastic/`).flush([]);
    http.expectOne(`${urlTaches}/`).flush([]);
    http.expectOne(`${environment.apiUrl}/configurations-noeuds-meshtastic/`).flush([]);
    http.expectOne(urlReglages).flush(null, { status: 503, statusText: 'Unavailable' });
    expect(fixture.componentInstance.sections).toEqual([]);
    expect(fixture.componentInstance.erreur).toBeNull();
  });
});
