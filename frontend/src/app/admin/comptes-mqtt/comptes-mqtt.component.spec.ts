import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ComptesMqttComponent } from './comptes-mqtt.component';
import { environment } from '../../../environments/environment';
import { CompteMqtt } from '../../shared/models/compte-mqtt.model';

const UN_COMPTE: CompteMqtt = {
  id: 'c1', nom: 'passerelle-mairie', role: 'RADIO', role_libelle: 'Passerelle',
  racine_topic: 'msh/EU_868', description: '', infrastructure: false, actif: true,
  date_creation: '2026-11-06T10:00:00Z', modifie_le: '2026-11-06T10:00:00Z',
};

describe('ComptesMqttComponent', () => {
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/comptes-mqtt`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ComptesMqttComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function creerComposant() {
    const fixture = TestBed.createComponent(ComptesMqttComponent);
    fixture.detectChanges();
    return fixture.componentInstance;
  }

  it('charge la liste au démarrage', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush([UN_COMPTE]);
    expect(composant.comptes.length).toBe(1);
    expect(composant.chargement).toBeFalse();
  });

  it('explique un refus 403 plutôt que d’afficher une erreur générique', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush(null, { status: 403, statusText: 'Forbidden' });
    expect(composant.erreur).toContain('administrateurs');
  });

  it('n’affiche aucun mot de passe tant qu’on ne le demande pas', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush([UN_COMPTE]);
    expect(composant.motsDePasseAffiches['c1']).toBeUndefined();

    composant.afficherMotDePasse('c1');
    http.expectOne(`${url}/c1/mot-de-passe/`).flush({ nom: 'x', mot_de_passe: 'secret-du-serveur' });
    expect(composant.motsDePasseAffiches['c1']).toBe('secret-du-serveur');

    composant.masquerMotDePasse('c1');
    expect(composant.motsDePasseAffiches['c1']).toBeUndefined();
  });

  it('ne régénère pas sans confirmation explicite', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush([UN_COMPTE]);

    // Demander la confirmation ne doit déclencher AUCUN appel : régénérer coupe la passerelle.
    composant.confirmerRegeneration('c1');
    expect(composant.regenerationDemandee).toBe('c1');
    http.expectNone(`${url}/c1/regenerer/`);

    composant.regenerer('c1');
    http.expectOne(`${url}/c1/regenerer/`).flush({ nom: 'x', mot_de_passe: 'nouveau' });
    expect(composant.motsDePasseAffiches['c1']).toBe('nouveau');
    expect(composant.regenerationDemandee).toBeNull();
    http.expectOne(`${url}/`).flush([UN_COMPTE]);
  });

  it('crée un compte sans envoyer de mot de passe et affiche celui du serveur', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush([]);

    composant.nouveau = { nom: ' gw-toit ', role: 'RADIO', racine_topic: 'msh/EU_868', description: '' };
    composant.creer();

    const creation = http.expectOne(`${url}/`);
    expect(creation.request.method).toBe('POST');
    expect(creation.request.body.nom).toBe('gw-toit');          // espaces retirés
    expect('mot_de_passe' in creation.request.body).toBeFalse(); // engendré par le serveur
    creation.flush({ ...UN_COMPTE, id: 'c2' });

    http.expectOne(`${url}/c2/mot-de-passe/`).flush({ nom: 'gw-toit', mot_de_passe: 'engendre' });
    expect(composant.motsDePasseAffiches['c2']).toBe('engendre');
    http.expectOne(`${url}/`).flush([]);
  });

  it('remonte le motif exact d’un refus de création', () => {
    const composant = creerComposant();
    http.expectOne(`${url}/`).flush([]);
    composant.nouveau.nom = 'trop large';
    composant.creer();
    http.expectOne(`${url}/`).flush(
      { nom: ['Nom de compte MQTT invalide : 2 à 63 caractères…'] },
      { status: 400, statusText: 'Bad Request' },
    );
    expect(composant.erreurCreation).toContain('invalide');
    expect(composant.creationEnCours).toBeFalse();
  });
});
