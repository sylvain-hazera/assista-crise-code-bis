import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { environment } from '../../../environments/environment';
import { fournisseursDeTest } from '../../testing/test-providers';
import { AlerteNaturelle, MatriceAlertes, PhenomeneAlerte } from '../../services/alertes-automatiques.service';
import { AlertesAutomatiquesComponent } from './alertes-automatiques.component';

const api = `${environment.apiUrl}/alertes-automatiques`;

const phenomene = (champs: Partial<PhenomeneAlerte>): PhenomeneAlerte => ({
  code: 'SEISME', libelle: 'Séisme', famille: 'Terre', unite: 'magnitude', conseille: { alerte: 3.5, exceptionnel: 4.5, rayon_km: 100 },
  minimum: 2, maximum: 7, pas: 0.1, radio_possible: true, reglages: { rayon_km: { defaut: 100, minimum: 10, maximum: 300 } },
  echelle: {}, source: { perime: false }, regle: null, derniere_alerte: null, ...champs,
});

const alerte: AlerteNaturelle = {
  id: 'a1', phenomene: 'SEISME', phenomene_libelle: 'Séisme', famille: 'Terre', niveau: 'EXCEPTIONNEL', valeur: 4.8,
  unite: 'magnitude', titre: 'Séisme de magnitude 4.8 à 8 km de Saint-Étienne', detail: 'Source : BCSF-Rénass / EMSC.',
  latitude: 45.5, longitude: 4.4, emise_le: '2026-11-24T12:00:00Z', bilan: { personnes: 3, courriels: 2, radio: 1 },
  institution: 'i1', crise: null, crise_nom: null, campagne: null, type_crise: 'CATASTROPHE_NATURELLE',
};

const matrice = (): MatriceAlertes => ({
  institution: { id: 'i1', nom: 'Mairie de Saint-Étienne' }, choix: [{ id: 'i1', nom: 'Mairie de Saint-Étienne' }],
  perimetre: { niveau: 'commune', code: '42218', communes: 1 },
  phenomenes: [
    phenomene({}),
    phenomene({ code: 'VIGILANCE_METEO', libelle: 'Vigilance Météo-France', famille: 'Météo', unite: 'couleur',
                conseille: { alerte: 3, exceptionnel: 4 }, minimum: 2, maximum: 5, reglages: {},
                echelle: { '2': 'jaune', '3': 'orange', '4': 'rouge', '5': 'violet' },
                regle: { id: 'r1', actif: true, seuils: { alerte: 3, exceptionnel: 4 }, email: true, radio_si_exceptionnel: true,
                         silence_nuit: true, destinataires: 'CONTACTS' } }),
    phenomene({ code: 'RESTRICTIONS_EAU', libelle: "Restrictions d'eau", famille: 'Eau', radio_possible: false, reglages: {},
                source: { perime: true } }),
  ],
  alertes: [alerte],
});

describe('Alertes automatiques (24/11/2026)', () => {
  let http: HttpTestingController;

  function creer() {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(AlertesAutomatiquesComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/`).flush(matrice());
    fixture.detectChanges();
    return fixture;
  }

  it('la matrice par famille, avec les valeurs conseillées et l’état des sources', () => {
    const fixture = creer();
    const page = fixture.nativeElement as HTMLElement;
    const familles = [...page.querySelectorAll('tr.famille')].map(e => e.textContent?.trim());
    expect(familles).toEqual(['Terre', 'Météo', 'Eau']);
    expect(page.textContent).toContain('1 alerte active sur 3');
    expect(page.querySelector('[data-code="RESTRICTIONS_EAU"]')?.textContent).toContain('en retard');
    // Pas de radio pour les restrictions d'eau.
    expect(page.querySelector('[data-code="RESTRICTIONS_EAU"] input[aria-label^="Radio"]')).toBeNull();
    const vigilance = page.querySelector('[data-code="VIGILANCE_METEO"] select') as HTMLSelectElement;
    expect([...vigilance.options].map(o => o.textContent?.trim())).toEqual(['jaune', 'orange', 'rouge', 'violet']);
  });

  it('activer une ligne l’enregistre avec ses seuils', () => {
    const fixture = creer();
    (fixture.nativeElement.querySelector('[data-code="SEISME"] .interrupteur') as HTMLButtonElement).click();
    const requete = http.expectOne(`${api}/regle/`);
    expect(requete.request.body).toEqual(jasmine.objectContaining({
      institution: 'i1', phenomene: 'SEISME', actif: true, email: true, radio_si_exceptionnel: true,
      seuils: { alerte: 3.5, exceptionnel: 4.5, rayon_km: 100 },
    }));
    requete.flush({ id: 'r2', actif: true, seuils: { alerte: 3.5, exceptionnel: 4.5, rayon_km: 100 }, email: true,
                    radio_si_exceptionnel: true, silence_nuit: true, destinataires: 'CONTACTS' });
    fixture.detectChanges();
    expect(fixture.componentInstance.message).toContain('Séisme : alerte active');
  });

  it('une alerte ouverte propose d’ouvrir une crise préremplie et de demander les disponibilités', () => {
    const fixture = creer();
    const router = TestBed.inject(Router);
    const navigation = spyOn(router, 'navigate').and.resolveTo(true);
    (fixture.nativeElement.querySelector('.alerte-ligne') as HTMLButtonElement).click();
    fixture.detectChanges();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Ouvrir une crise');
    expect(texte).toContain('Préparer le déclenchement : demander les disponibilités');
    expect(texte).toContain('radio sur 1 canal');

    fixture.componentInstance.ouvrirUneCrise(alerte);
    http.expectOne(`${api}/a1/crise/`).flush({ type: 'CATASTROPHE_NATURELLE', titre: alerte.titre, description: 'x',
                                               latitude: 45.5, longitude: 4.4, institution: 'i1' });
    expect(navigation).toHaveBeenCalledWith(['/crisis-declaration'], jasmine.objectContaining({
      queryParams: jasmine.objectContaining({ type: 'CATASTROPHE_NATURELLE', alerte: 'a1' }),
    }));

    fixture.componentInstance.demanderDisponibilites(alerte);
    http.expectOne(`${api}/a1/disponibilites/`).flush({ ...alerte, campagne: 'c9', campagne_creee: true });
    expect(navigation).toHaveBeenCalledWith(['/admin/campagnes-disponibilite'],
                                            { queryParams: { institution: 'i1', campagne: 'c9' } });
  });
});
