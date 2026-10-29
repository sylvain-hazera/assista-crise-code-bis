import { HttpErrorResponse } from '@angular/common/http';
import { fakeAsync, tick } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { SimulationInondationComponent } from './simulation-inondation.component';
import { LocationService } from '../../services/location.service';
import { SimulationInondationService } from '../../services/simulation-inondation.service';

/** Constaté en production le 29/10/2026 : une personne dont l'institution couvre Le Porge a
 * ouvert Arès puis Andernos-les-Bains, hors de son secteur. Le serveur répondait 403 avec un
 * motif parfaitement clair, et l'écran affichait « Échec de la simulation […] contacter le
 * support si le problème persiste » — une panne, là où il n'y avait qu'une frontière de droits.
 *
 * Le composant est instancié à la main, sans TestBed : son `ngAfterViewInit` construit une
 * carte MapLibre qui ne s'initialise pas sous Chrome headless, et ce qui est vérifié ici ne
 * tient qu'à la gestion d'erreur. `fakeAsync` parce que `pollWhileVisible` part d'un
 * `timer(0, …)` : la réponse n'arrive donc jamais dans le même tour que l'appel. */
describe('SimulationInondationComponent — message d\'erreur du serveur', () => {
  let simulation: jasmine.SpyObj<SimulationInondationService>;
  let location: jasmine.SpyObj<LocationService>;

  const refus = new HttpErrorResponse({
    status: 403,
    error: { error: "Vous n'avez pas accès à cette commune pour cet outil." },
  });
  const ARES = { code: '33011', nom: 'Arès' } as never;

  function composant(): SimulationInondationComponent {
    const c = new SimulationInondationComponent(location, simulation);
    // Pas de carte en test : la sélection d'une commune essaierait de la cadrer.
    spyOn(c as never as { cadrerSurCommune: () => void }, 'cadrerSurCommune');
    return c;
  }

  beforeEach(() => {
    simulation = jasmine.createSpyObj<SimulationInondationService>(
      'SimulationInondationService',
      ['simuler', 'chargerAdresses', 'chargerRuissellement', 'niveauObserve',
       'zonesGeorisques', 'perimetre'],
    );
    simulation.niveauObserve.and.returnValue(of(null) as never);
    simulation.perimetre.and.returnValue(of({ portee: 'nationale', libelle: 'France entière' }) as never);
    location = jasmine.createSpyObj<LocationService>(
      'LocationService', ['searchCommunesByName', 'getCommuneContour'],
    );
    location.getCommuneContour.and.returnValue(of(null) as never);
  });

  it('affiche le motif du refus plutôt qu\'une invitation à réessayer', fakeAsync(() => {
    simulation.simuler.and.returnValue(throwError(() => refus));
    const c = composant();

    c.choisirCommune(ARES);
    tick();

    expect(c.erreur).toBe("Vous n'avez pas accès à cette commune pour cet outil.");
    expect(c.erreur).not.toContain('support');
  }));

  it('affiche le motif du refus au chargement des adresses', fakeAsync(() => {
    simulation.chargerAdresses.and.returnValue(throwError(() => refus));
    const c = composant();
    c.communeSelectionnee = ARES;

    c.chargerAdresses();
    tick();

    expect(c.adressesErreur).toBe("Vous n'avez pas accès à cette commune pour cet outil.");
  }));

  it('borne la recherche de communes au secteur annoncé', () => {
    const c = composant();
    c.perimetre = { portee: 'secteur', libelle: 'CC Médullienne', niveau: 'epci',
                    champ: 'codeEpci', valeur: '243301389' };

    c.communeSearchFn('por');

    expect(location.searchCommunesByName).toHaveBeenCalledWith(
      'por', { champ: 'codeEpci', valeur: '243301389' });
    expect(c.explicationPerimetre).toContain('CC Médullienne');
    expect(c.perimetreVide).toBeFalse();
  });

  it('ne borne rien tant que le périmètre est inconnu', () => {
    const c = composant();
    c.perimetre = null;

    c.communeSearchFn('por');

    expect(location.searchCommunesByName).toHaveBeenCalledWith('por', null);
  });

  it('annonce explicitement qu\'aucune commune n\'est ouverte', () => {
    const c = composant();
    c.perimetre = { portee: 'aucune', libelle: '' };

    expect(c.perimetreVide).toBeTrue();
    expect(c.explicationPerimetre).toContain('rattachés à une collectivité');
  });

  it('retombe sur un message générique quand le corps est inexploitable', fakeAsync(() => {
    simulation.simuler.and.returnValue(
      throwError(() => new HttpErrorResponse({ status: 502, error: '<html>502</html>' })));
    const c = composant();

    c.choisirCommune(ARES);
    tick();

    expect(c.erreur).toContain('Échec de la simulation');
  }));
});
