import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { of } from 'rxjs';

import { VerificationMobilisationComponent } from './verification-mobilisation.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';

/**
 * Page ouverte par le QR code — le chemin de l'iPhone.
 *
 * Ce qui est testé est ce qui décide d'une conduite sur le terrain :
 *
 * 1. **le verdict réduit est annoncé comme tel**, jamais présenté comme un verdict complet aux
 *    champs manquants : « pas de destinataire affiché » et « destinataire inconnu » ne sont
 *    pas la même chose ;
 * 2. **une panne réseau n'est pas une attestation invalide.** Confondre les deux ferait
 *    refouler quelqu'un sur une erreur de serveur ;
 * 3. **la route fonctionne sans être connecté**, parce qu'un contrôleur extérieur doit pouvoir
 *    vérifier l'authenticité d'un document.
 */
describe('VerificationMobilisationComponent', () => {
  let http: HttpTestingController;
  const api = environment.apiUrl;

  function creer(jeton: string | null, connecte: boolean) {
    const vide = convertToParamMap(jeton ? { jeton } : {});
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        ...fournisseursDeTest(),
        { provide: ActivatedRoute, useValue: {
          snapshot: { paramMap: vide, queryParamMap: convertToParamMap({}) },
          paramMap: of(vide), queryParamMap: of(convertToParamMap({})),
        } },
        { provide: AuthService, useValue: { getToken: () => (connecte ? 'jeton' : null) } },
      ],
      imports: [VerificationMobilisationComponent],
    });
    const fixture = TestBed.createComponent(VerificationMobilisationComponent);
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    return fixture;
  }

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  it('interroge la vérification avec le jeton du lien', () => {
    const fixture = creer('abc123', false);

    http.expectOne(`${api}/verifier-mobilisation/abc123/donnees/`).flush({
      valide: true, connue: true, complet: false, motif: 'Attestation valide.',
      reference: '4F2A1B', institution_emettrice: 'Mairie de X', crise: 'Crue',
      nature: 'Se rendre à un endroit précis',
    });
    fixture.detectChanges();

    const texte = fixture.nativeElement.textContent;
    expect(texte).toContain('ATTESTATION VALIDE');
    expect(texte).toContain('Mairie de X');
  });

  it('annonce que le détail est retenu faute d\'authentification', () => {
    const fixture = creer('abc123', false);
    http.expectOne(r => r.url.includes('/verifier-mobilisation/')).flush({
      valide: true, connue: true, complet: false, motif: 'Attestation valide.',
      reference: '4F2A1B', institution_emettrice: 'Mairie de X', crise: 'Crue',
      nature: 'Se rendre à un endroit précis',
    });
    fixture.detectChanges();

    // Dit, et non laissé deviner : un champ absent se lirait comme une donnée manquante.
    const texte = fixture.nativeElement.textContent;
    expect(texte).toContain('ne sont pas affichés');
    expect(texte).toContain('Se connecter');
  });

  it('affiche le destinataire pour un compte connecté, sans proposer de connexion', () => {
    const fixture = creer('abc123', true);
    http.expectOne(r => r.url.includes('/verifier-mobilisation/')).flush({
      valide: true, connue: true, complet: true, motif: 'Attestation valide.',
      reference: '4F2A1B', institution_emettrice: 'Mairie de X', crise: 'Crue',
      nature: 'Se rendre à un endroit précis', destinataire: 'Jean Cible',
      lieu: 'Salle des fêtes',
    });
    fixture.detectChanges();

    const texte = fixture.nativeElement.textContent;
    expect(texte).toContain('Jean Cible');
    expect(texte).toContain('Salle des fêtes');
    expect(texte).not.toContain('ne sont pas affichés');
  });

  it('distingue un code inconnu d\'une révocation', () => {
    const fixture = creer('inconnu', false);
    http.expectOne(r => r.url.includes('/verifier-mobilisation/')).flush({
      valide: false, connue: false, motif: 'Aucune attestation ne correspond à ce QR code.',
    });
    fixture.detectChanges();

    // « Ce QR n'est pas des nôtres » n'appelle pas la même réaction que « révoquée ».
    expect(fixture.nativeElement.textContent).toContain('CODE INCONNU');
  });

  it('ne conclut rien d\'une panne réseau', () => {
    const fixture = creer('abc123', false);
    http.expectOne(r => r.url.includes('/verifier-mobilisation/')).flush(
      {}, { status: 503, statusText: 'Service Unavailable' });
    fixture.detectChanges();

    const texte = fixture.nativeElement.textContent;
    expect(texte).toContain('Ne concluez rien');
    // Et surtout : aucun verdict affiché, ni valide ni invalide.
    expect(texte).not.toContain('ATTESTATION');
  });

  it('dit qu\'un lien incomplet est incomplet', () => {
    const fixture = creer(null, false);

    expect(fixture.nativeElement.textContent).toContain('incomplet');
    http.expectNone(r => r.url.includes('/verifier-mobilisation/'));
  });
});
