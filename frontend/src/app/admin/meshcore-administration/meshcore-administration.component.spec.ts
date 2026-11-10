import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { MeshcoreAdministrationComponent } from './meshcore-administration.component';
import { environment } from '../../../environments/environment';

const API = environment.apiUrl;

/** Un répéteur MeshCore réclamé, preuve faite. */
const VERIFIE = {
  id: 'r1', node_num: null, pubkey_hex: 'ab'.repeat(32), protocole: 'MESHCORE',
  institution: 'i1', institution_nom: 'Mairie', utilisateur: null, utilisateur_nom: null,
  responsable: 'Mairie de Saint-Pierre', libelle: 'Répéteur du piton', note: '',
  moyen_admin: 'MOT_DE_PASSE', moyen_admin_libelle: "Mot de passe d'administration",
  compagnon_meshcore: 'c1', statut_preuve: 'VERIFIEE', statut_preuve_libelle: 'Contrôle démontré',
  preuve_faite: true, date_verification: '2026-11-10T10:00:00Z', erreur_verification: '',
};

/** Le même, sans preuve : toute écriture doit être refusée AVANT le clic. */
const SANS_PREUVE = {
  ...VERIFIE, id: 'r2', pubkey_hex: 'cd'.repeat(32), libelle: 'Répéteur douteux',
  statut_preuve: 'NON_VERIFIE', statut_preuve_libelle: 'Pas encore vérifiée', preuve_faite: false,
};

/** Un rattachement Meshtastic : la même table le porte, cette page ne doit pas l'afficher. */
const MESHTASTIC = {
  ...VERIFIE, id: 'r3', node_num: 0x1234, pubkey_hex: '', protocole: 'MESHTASTIC',
  libelle: 'Nœud Meshtastic', moyen_admin: 'AUCUN',
};

describe('MeshcoreAdministrationComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MeshcoreAdministrationComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer(rattachements: any[] = [VERIFIE], taches: any[] = []) {
    const fixture = TestBed.createComponent(MeshcoreAdministrationComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/rattachements-noeuds-radio/`).flush(rattachements);
    http.expectOne(`${API}/compagnons-meshcore/`).flush([
      { id: 'c1', nom: 'Companion mairie', actif: true },
      { id: 'c2', nom: 'Companion retire', actif: false },
    ]);
    http.expectOne(`${API}/taches-admin-meshcore/`).flush(taches);
    fixture.detectChanges();
    return fixture;
  }

  it('ne montre que les répéteurs MeshCore, pas les nœuds Meshtastic', () => {
    // La même table porte les deux : un nœud Meshtastic s'administre depuis sa propre page et
    // par un tout autre mécanisme.
    const fixture = demarrer([VERIFIE, MESHTASTIC]);
    expect(fixture.componentInstance.rattachements.map(r => r.id)).toEqual(['r1']);
  });

  it('ne propose que les companions actifs', () => {
    const fixture = demarrer();
    expect(fixture.componentInstance.companions.map(c => c.id)).toEqual(['c1']);
  });

  it('refuse une écriture AVANT le clic quand la preuve n\'est pas faite', () => {
    // Le serveur refuserait de toute façon ; le dire avant évite de le faire découvrir par un
    // 403 trois minutes plus tard.
    const fixture = demarrer([SANS_PREUVE]);
    const composant = fixture.componentInstance;
    composant.operation.rattachement = 'r2';
    composant.operation.type = 'REDEMARRER';
    expect(composant.ecritureImpossible).toBeTrue();

    // Une lecture, en revanche, reste possible : relever un statut n'est pas un acte matériel.
    composant.operation.type = 'LIRE_STATUT';
    expect(composant.ecritureImpossible).toBeFalse();
  });

  it('une écriture passe quand la preuve est faite', () => {
    const fixture = demarrer([VERIFIE]);
    const composant = fixture.componentInstance;
    composant.operation.rattachement = 'r1';
    composant.operation.type = 'REDEMARRER';
    expect(composant.ecritureImpossible).toBeFalse();
  });

  it('l\'essai radio envoie les cinq paramètres, délai de retour compris', () => {
    const fixture = demarrer();
    const composant = fixture.componentInstance;
    composant.operation.rattachement = 'r1';
    composant.operation.type = 'RADIO_TEMPORAIRE';
    composant.operation.frequence_mhz = 869.4625;
    composant.operation.minutes = 5;
    composant.lancer();

    const envoi = http.expectOne(`${API}/taches-admin-meshcore/`);
    expect(envoi.request.body.compagnon).toBe('c1');
    expect(envoi.request.body.pubkey_cible).toBe(VERIFIE.pubkey_hex);
    expect(envoi.request.body.parametres).toEqual({
      frequence_mhz: 869.4625, bande_khz: 250, facteur_etalement: 11,
      taux_codage: 5, minutes: 5,
    });
    envoi.flush({});
    http.expectOne(`${API}/taches-admin-meshcore/`).flush([]);
  });

  it('une lecture n\'envoie aucun paramètre', () => {
    const fixture = demarrer();
    fixture.componentInstance.operation.rattachement = 'r1';
    fixture.componentInstance.operation.type = 'LIRE_VOISINS';
    fixture.componentInstance.lancer();

    const envoi = http.expectOne(`${API}/taches-admin-meshcore/`);
    expect(envoi.request.body.parametres).toBeNull();
    envoi.flush({});
    http.expectOne(`${API}/taches-admin-meshcore/`).flush([]);
  });

  it('la voie ACL n\'envoie pas de mot de passe', () => {
    // Le serveur refuse les deux à la fois : la clé du companion suffit, le répéteur la
    // reconnaît par son ACL.
    const fixture = demarrer();
    const composant = fixture.componentInstance;
    composant.reclamation.pubkey_hex = 'EF'.repeat(32);
    composant.reclamation.moyen_admin = 'ACL';
    composant.reclamation.mot_de_passe = 'residu-de-saisie';
    composant.reclamation.compagnon_meshcore = 'c1';
    composant.reclamer();

    const envoi = http.expectOne(`${API}/rattachements-noeuds-radio/`);
    expect(envoi.request.body.moyen_admin).toBe('ACL');
    expect(envoi.request.body.mot_de_passe).toBe('');
    // La clé est normalisée en minuscules : le serveur compare des minuscules.
    expect(envoi.request.body.pubkey_hex).toBe('ef'.repeat(32));
    envoi.flush({});

    http.expectOne(`${API}/rattachements-noeuds-radio/`).flush([VERIFIE]);
    http.expectOne(`${API}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${API}/taches-admin-meshcore/`).flush([]);
  });

  it('la vérification est relançable et relit l\'état ensuite', () => {
    const fixture = demarrer([SANS_PREUVE]);
    fixture.componentInstance.verifier(SANS_PREUVE as any);

    http.expectOne(`${API}/rattachements-noeuds-radio/r2/verifier/`).flush({});
    http.expectOne(`${API}/rattachements-noeuds-radio/`).flush([{ ...SANS_PREUVE, statut_preuve: 'EN_ATTENTE' }]);
    http.expectOne(`${API}/compagnons-meshcore/`).flush([]);
    http.expectOne(`${API}/taches-admin-meshcore/`).flush([]);
    expect(fixture.componentInstance.rattachements[0].statut_preuve).toBe('EN_ATTENTE');
  });

  it('affiche le message du serveur, qui dit la vraie raison', () => {
    const fixture = demarrer();
    const composant = fixture.componentInstance;
    composant.operation.rattachement = 'r1';
    composant.operation.type = 'DEFINIR_REGLAGE';
    composant.operation.cle = 'prv.key';
    composant.operation.valeur = 'x';
    composant.lancer();

    http.expectOne(`${API}/taches-admin-meshcore/`).flush(
      { cle: ["Change l'identité du nœud : son trafic passé devient indéchiffrable."] },
      { status: 400, statusText: 'Bad Request' },
    );
    expect(composant.erreurOperation).toContain("identité du nœud");
  });

  it('une réponse illisible est affichée telle quelle, pas masquée', () => {
    // C'est souvent là qu'est l'indice quand le pont rend autre chose que du JSON.
    const fixture = demarrer();
    expect(fixture.componentInstance.reponseLisible(
      { reponse: 'pas du json' } as any,
    )).toBe('pas du json');
    expect(fixture.componentInstance.reponseLisible(
      { reponse: '{"a":1}' } as any,
    )).toContain('"a": 1');
  });
});
