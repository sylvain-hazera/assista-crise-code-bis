import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { VerificationMobilisationService } from './verification-mobilisation.service';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';

/**
 * L'extraction du jeton est la seule logique de ce service, et elle décide de ce qui part au
 * serveur. Deux risques qu'elle doit tenir :
 *
 * 1. **un QR étranger ne doit pas partir en requête.** Une carte de visite, un billet de
 *    train : l'écran doit dire « ce code n'est pas une attestation », pas « introuvable », qui
 *    laisserait croire à une attestation périmée.
 * 2. **le jeton nu doit être accepté**, parce que c'est la saisie manuelle — le seul chemin
 *    disponible sur iPhone, où le navigateur ne sait pas décoder un QR.
 */
describe('VerificationMobilisationService', () => {
  let service: VerificationMobilisationService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    service = TestBed.inject(VerificationMobilisationService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  describe('le jeton lu', () => {
    it('est extrait de l\'URL complète du QR', () => {
      const jeton = 'AbC-123_xyzAbC123xyzAbC123xyz';
      expect(service.jetonDepuisTexte(
        `https://www.assista-crise.fr/api/verifier-mobilisation/${jeton}/`)).toBe(jeton);
    });

    it('survit à une URL sans barre oblique finale ou avec des paramètres', () => {
      const jeton = 'AbC-123_xyzAbC123xyzAbC123xyz';
      expect(service.jetonDepuisTexte(
        `https://exemple.invalide/api/verifier-mobilisation/${jeton}`)).toBe(jeton);
      expect(service.jetonDepuisTexte(
        `https://exemple.invalide/api/verifier-mobilisation/${jeton}?src=qr`)).toBe(jeton);
    });

    it('accepte un jeton nu, pour la saisie manuelle', () => {
      // Le seul chemin disponible sur iPhone : le refuser priverait ces téléphones de toute
      // vérification intégrée.
      expect(service.jetonDepuisTexte('AbC-123_xyzAbC123xyzAbC123xyz'))
        .toBe('AbC-123_xyzAbC123xyzAbC123xyz');
    });

    it('refuse un QR qui n\'a rien à voir', () => {
      expect(service.jetonDepuisTexte('https://exemple.invalide/carte-de-visite')).toBeNull();
      expect(service.jetonDepuisTexte('BEGIN:VCARD')).toBeNull();
      expect(service.jetonDepuisTexte('')).toBeNull();
      // Trop court pour être un jeton : `token_urlsafe(32)` en fait 43.
      expect(service.jetonDepuisTexte('abc')).toBeNull();
    });

    it('ignore les espaces autour', () => {
      expect(service.jetonDepuisTexte('  AbC-123_xyzAbC123xyzAbC123xyz  '))
        .toBe('AbC-123_xyzAbC123xyzAbC123xyz');
    });
  });

  describe('la vérification', () => {
    it('interroge l\'endpoint public et rend le verdict', () => {
      let verdict: unknown = null;
      service.verifier('jeton-abc').subscribe(v => verdict = v);

      const requete = http.expectOne(
        `${environment.apiUrl}/verifier-mobilisation/jeton-abc/donnees/`);
      expect(requete.request.method).toBe('GET');
      requete.flush({ valide: true, connue: true, motif: 'Attestation valide.' });

      expect((verdict as { valide: boolean }).valide).toBeTrue();
    });

    it('échappe le jeton dans l\'URL', () => {
      // Un jeton mal lu ne doit pas pouvoir sortir du chemin prévu.
      service.verifier('a/b?c').subscribe();
      http.expectOne(
        `${environment.apiUrl}/verifier-mobilisation/a%2Fb%3Fc/donnees/`).flush({
          valide: false, connue: false, motif: 'Inconnu.' });
    });
  });
});
