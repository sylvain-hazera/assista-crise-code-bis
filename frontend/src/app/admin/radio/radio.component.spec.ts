import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { RadioComponent } from './radio.component';
import { AuthService } from '../../auth/services/auth.service';
import { UserRole } from '../../shared/models/user.model';
import { EtatAccesRadio } from '../../shared/models/acces-radio.model';
import { environment } from '../../../environments/environment';

const SANS_ACCES: EtatAccesRadio = {
  niveau: 'AUCUN',
  niveau_libelle: 'Aucun accès radio',
  motifs: [],
  nombre_noeuds_personnels: 0,
  demande: null,
  titres_possibles: ['Rattacher un nœud personnel à votre compte.'],
};

const OPERATEUR: EtatAccesRadio = {
  niveau: 'OPERATEUR',
  niveau_libelle: 'Opérateur radio (ses propres nœuds)',
  motifs: ['1 nœud personnel actif rattaché à ce compte.'],
  nombre_noeuds_personnels: 1,
  demande: null,
  titres_possibles: [],
};

describe('RadioComponent', () => {
  let http: HttpTestingController;
  let auth: jasmine.SpyObj<AuthService>;
  const urlMonAcces = `${environment.apiUrl}/demandes-acces-radio/mon-acces/`;

  beforeEach(() => {
    auth = jasmine.createSpyObj<AuthService>('AuthService', ['getCurrentUser']);
    auth.getCurrentUser.and.returnValue({ type: UserRole.RESCUE } as any);

    TestBed.configureTestingModule({
      imports: [RadioComponent],
      providers: [
        provideHttpClient(), provideHttpClientTesting(), provideRouter([]),
        { provide: AuthService, useValue: auth },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer(etat: EtatAccesRadio) {
    const fixture = TestBed.createComponent(RadioComponent);
    fixture.detectChanges();
    http.expectOne(urlMonAcces).flush(etat);
    fixture.detectChanges();
    return fixture;
  }

  it('sans accès, la page propose de demander le droit et dit ce qui manque', () => {
    const fixture = demarrer(SANS_ACCES);
    const texte = fixture.nativeElement.textContent as string;

    expect(fixture.componentInstance.aAcces).toBeFalse();
    expect(texte).toContain('Rattacher un nœud personnel');
    expect(texte).toContain('Envoyer la demande');
    // Le sommaire des écrans radio n'a aucun sens pour qui ne peut pas les ouvrir.
    expect(texte).not.toContain('Diagnostic radio');
  });

  it('avec accès, la page dit à quel titre et ouvre le sommaire', () => {
    const fixture = demarrer(OPERATEUR);
    const texte = fixture.nativeElement.textContent as string;

    expect(fixture.componentInstance.aAcces).toBeTrue();
    expect(texte).toContain('1 nœud personnel actif');
    expect(texte).toContain('Diagnostic radio');
    // Un opérateur n'administre PAS les passerelles : la page doit le dire, pas le laisser
    // découvrir par un 403.
    expect(texte).toContain('vos propres nœuds');
  });

  it('un motif vide n\'est pas envoyé', () => {
    const fixture = demarrer(SANS_ACCES);
    fixture.componentInstance.motif = '   ';
    fixture.componentInstance.envoyerDemande();
    // Rien ne part : http.verify() de afterEach échouerait sur une requête en trop.
    expect(fixture.componentInstance.envoi).toBeFalse();
  });

  it('la demande envoyée relit l\'état complet au lieu de le deviner', () => {
    const fixture = demarrer(SANS_ACCES);
    fixture.componentInstance.motif = 'Je porte un T-Beam pour l\'équipe de Saint-Pierre.';
    fixture.componentInstance.envoyerDemande();

    const envoi = http.expectOne(`${environment.apiUrl}/demandes-acces-radio/`);
    expect(envoi.request.method).toBe('POST');
    expect(envoi.request.body.niveau_demande).toBe('OPERATEUR');
    envoi.flush({});

    // Le serveur seul sait si le droit vient de s'ouvrir par un autre titre entre-temps.
    http.expectOne(urlMonAcces).flush(OPERATEUR);
    expect(fixture.componentInstance.aAcces).toBeTrue();
  });

  it('le message du serveur est affiché tel quel', () => {
    const fixture = demarrer(SANS_ACCES);
    fixture.componentInstance.motif = 'Un nœud.';
    fixture.componentInstance.envoyerDemande();
    http.expectOne(`${environment.apiUrl}/demandes-acces-radio/`).flush(
      { non_field_errors: ['Vous avez déjà une demande en attente d\'instruction.'] },
      { status: 400, statusText: 'Bad Request' },
    );
    expect(fixture.componentInstance.erreurEnvoi).toContain('déjà une demande en attente');
  });

  it('seul un administrateur réel charge et instruit les demandes', () => {
    auth.getCurrentUser.and.returnValue({ type: UserRole.ADMIN } as any);
    const fixture = TestBed.createComponent(RadioComponent);
    fixture.detectChanges();
    http.expectOne(urlMonAcces).flush(OPERATEUR);

    const liste = http.expectOne(
      r => r.url === `${environment.apiUrl}/demandes-acces-radio/` && r.params.get('statut') === 'EN_ATTENTE',
    );
    liste.flush([{
      id: 'd1', utilisateur: 'u1', utilisateur_nom: 'Dupont', utilisateur_email: 'a@b.fr',
      niveau_demande: 'ADMINISTRATEUR', niveau_demande_libelle: 'Administration radio complète',
      motif: 'Je gère le répéteur du château d\'eau.', statut: 'EN_ATTENTE',
      statut_libelle: "En attente d'instruction", niveau_accorde: null,
      instruite_par: null, instruite_par_nom: null, commentaire_decision: '',
      date_demande: '2026-11-10T08:00:00Z', date_decision: null,
    }]);
    fixture.detectChanges();

    // Le niveau proposé par défaut est celui demandé : l'instructeur l'abaisse s'il le juge.
    expect(fixture.componentInstance.niveauxAccordes['d1']).toBe('ADMINISTRATEUR');

    fixture.componentInstance.instruire(fixture.componentInstance.demandes[0], 'REFUSEE');
    const instruction = http.expectOne(`${environment.apiUrl}/demandes-acces-radio/d1/instruire/`);
    // Un refus n'accorde aucun niveau, même pas celui demandé.
    expect(instruction.request.body).toEqual({ decision: 'REFUSEE', niveau_accorde: null, commentaire: '' });
    instruction.flush({});

    http.expectOne(urlMonAcces).flush(OPERATEUR);
    http.expectOne(
      r => r.url === `${environment.apiUrl}/demandes-acces-radio/` && r.params.get('statut') === 'EN_ATTENTE',
    ).flush([]);
  });
});
