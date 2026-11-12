import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CanActivateFn, provideRouter } from '@angular/router';

import { AdminSidebarComponent } from './admin-sidebar.component';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { GROUPES_NAV, NAV_ITEMS, SOUS_GROUPES_NAV } from '../admin-nav.config';
import { ADMIN_ROUTES } from '../../../admin/admin.routes';
import {
  accountValidationGuard, institutionalEffectiveGuard, sysAdminGuard, vulnerabilitesGuard, autoriteLocaleGuard,
  membresAssociationGuard, radioGuard,
} from '../../../core/guards/admin.guard';

describe('AdminSidebarComponent', () => {
  let component: AdminSidebarComponent;
  let fixture: ComponentFixture<AdminSidebarComponent>;
  let auth: jasmine.SpyObj<AuthService>;

  const item = (label: string) => NAV_ITEMS.find(i => i.label === label)!;

  beforeEach(async () => {
    auth = jasmine.createSpyObj<AuthService>('AuthService', [
      'isSysAdmin', 'getEffectiveRole', 'isAutoriteLocaleCommunale', 'getCurrentUser', 'isInstitutionalEffective',
    ]);
    auth.isSysAdmin.and.returnValue(false);
    auth.getEffectiveRole.and.returnValue(UserRole.SIMPLE_USER);
    auth.isAutoriteLocaleCommunale.and.returnValue(false);
    auth.getCurrentUser.and.returnValue(null);
    auth.isInstitutionalEffective.and.returnValue(false);

    await TestBed.configureTestingModule({
      imports: [AdminSidebarComponent],
      providers: [provideRouter([]), { provide: AuthService, useValue: auth }],
    })
    .compileComponents();

    fixture = TestBed.createComponent(AdminSidebarComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('chaque route du menu est unique', () => {
    const routes = NAV_ITEMS.map(i => i.route);
    expect(new Set(routes).size).toBe(routes.length);
  });

  it('un compte sans aucun droit ne voit que les portes d\'entrée', () => {
    // Trois entrées, et toutes les trois pour la même raison : elles EXPLIQUENT ce qu'il
    // faut pour s'en servir au lieu de disparaître. « Accueil radio » dit comment obtenir la
    // radio et permet de la demander ; « Mes interventions » et « Hébergement » disent, quand
    // le compte n'est dans aucune équipe, pourquoi la page est vide et à qui s'adresser
    // (demande du 12/11/2026). Les masquer laisserait croire que ces fonctions n'existent pas.
    const visibles = NAV_ITEMS.filter(i => component.isNavItemVisible(i)).map(i => i.label);
    expect(visibles).toEqual(['Mes interventions', 'Hébergement', 'Accueil radio']);
  });

  it('les pages radio suivent `acces_radio`, pas le rôle', () => {
    // Un institutionnel SANS matériel radio ne voit aucune page radio : elles ne lui diraient
    // rien, et il est renvoyé vers « Accueil radio » s'il force l'URL (radioGuard).
    auth.isInstitutionalEffective.and.returnValue(true);
    expect(component.isNavItemVisible(item('Carte radio'))).toBeFalse();
    expect(component.isNavItemVisible(item('Companions Meshtastic (test)'))).toBeFalse();
    expect(component.isNavItemVisible(item('Accueil radio'))).toBeTrue();

    // Un porteur de nœud NON institutionnel les voit toutes : c'est le droit intermédiaire.
    auth.isInstitutionalEffective.and.returnValue(false);
    auth.getCurrentUser.and.returnValue({ acces_radio: true } as any);
    expect(component.isNavItemVisible(item('Carte radio'))).toBeTrue();
    expect(component.isNavItemVisible(item('Administration Meshtastic'))).toBeTrue();
    // Mais rien d'autre : un satellite est une machine, pas un poste radio.
    expect(component.isNavItemVisible(item('Satellites'))).toBeFalse();
    expect(component.isNavItemVisible(item('Signalements'))).toBeFalse();
  });

  describe('sous-cadres du menu', () => {
    beforeEach(() => {
      auth.isInstitutionalEffective.and.returnValue(true);
      auth.getCurrentUser.and.returnValue({ acces_radio: true } as any);
    });

    it('les entrées d\'un sous-cadre ne sont pas répétées dans le cadre', () => {
      const directes = component.itemsDirectsDuGroupe('communications').map(i => i.label);
      const dansSousCadre = [
        ...component.itemsDuSousGroupe('meshcore'),
        ...component.itemsDuSousGroupe('meshtastic'),
      ].map(i => i.label);

      expect(directes).toContain('Accueil radio');
      expect(dansSousCadre).toContain('Canaux MeshCore (test)');
      expect(directes.filter(l => dansSousCadre.includes(l))).toEqual([]);
      // Le mode réduit affiche tout à plat : la somme des deux doit couvrir le cadre entier.
      expect(directes.length + dansSousCadre.length)
        .toBe(component.itemsDuGroupe('communications').length);
    });

    it('un sous-cadre sans entrée visible n\'est pas affiché', () => {
      auth.getCurrentUser.and.returnValue(null);   // plus de droit radio
      expect(component.sousGroupesDuGroupe('communications')).toEqual([]);
    });

    it('chaque sous-cadre appartient à un cadre qui existe', () => {
      const cadres = GROUPES_NAV.map(g => g.id);
      const orphelins = SOUS_GROUPES_NAV.filter(s => !cadres.includes(s.groupe)).map(s => s.id);
      expect(orphelins).toEqual([]);
    });

    it('chaque entrée à sous-cadre déclare le cadre de ce sous-cadre', () => {
      // Sinon l'entrée disparaît : elle n'est ni directe dans son cadre, ni dans le cadre où
      // son sous-cadre est rendu.
      const incoherentes = NAV_ITEMS
        .filter(i => i.sousGroupe)
        .filter(i => SOUS_GROUPES_NAV.find(s => s.id === i.sousGroupe)?.groupe !== i.groupe)
        .map(i => i.route);
      expect(incoherentes).toEqual([]);
    });
  });

  it('un institutionnel voit les entrées par défaut, pas celles des admins', () => {
    auth.isInstitutionalEffective.and.returnValue(true);
    expect(component.isNavItemVisible(item('Signalements'))).toBeTrue();
    expect(component.isNavItemVisible(item('Utilisateurs'))).toBeFalse();
    expect(component.isNavItemVisible(item('Zones'))).toBeFalse();
  });

  it('les règles particulières suivent AuthService', () => {
    auth.isSysAdmin.and.returnValue(true);
    auth.isAutoriteLocaleCommunale.and.returnValue(true);
    auth.getEffectiveRole.and.returnValue(UserRole.LOCAL_AUTH);
    expect(component.isNavItemVisible(item('Utilisateurs'))).toBeTrue();
    expect(component.isNavItemVisible(item('Main courante'))).toBeTrue();
    expect(component.isNavItemVisible(item('Zones'))).toBeTrue();
    expect(component.isNavItemVisible(item('Simulation inondation'))).toBeTrue();
    expect(component.isNavItemVisible(item('Validations de comptes'))).toBeTrue();
    expect(component.isNavItemVisible(item('Personnes vulnérables'))).toBeFalse();
  });

  describe('alignement avec admin.routes.ts', () => {
    const gardeAttendue: Record<string, CanActivateFn> = {
      institutionnel: institutionalEffectiveGuard,
      sysadmin: sysAdminGuard,
      'validation-comptes': accountValidationGuard,
      'autorite-locale': autoriteLocaleGuard,
      'registre-vulnerables': vulnerabilitesGuard,
      'membres-association': membresAssociationGuard,
      radio: radioGuard,
    };
    const routeDe = (navRoute: string) =>
      ADMIN_ROUTES.find(r => `/admin/${r.path}` === navRoute);
    const entreesAdmin = NAV_ITEMS.filter(i => i.route.startsWith('/admin/'));

    it('chaque entrée /admin/... du menu correspond à une route', () => {
      const sansRoute = entreesAdmin.filter(i => !routeDe(i.route)).map(i => i.route);
      expect(sansRoute).toEqual([]);
    });

    it('la route de chaque entrée a la garde qui correspond à sa visibilité', () => {
      const incoherences = entreesAdmin
        .filter(i => i.visibilite !== 'tous')
        .filter(i => !(routeDe(i.route)?.canActivate ?? []).includes(gardeAttendue[i.visibilite ?? 'institutionnel']))
        .map(i => `${i.route} (${i.visibilite ?? 'institutionnel'})`);
      expect(incoherences).toEqual([]);
    });
  });

  it('le mode réduit pose la classe `collapsed` sur l\'élément hôte', () => {
    fixture.componentRef.setInput('collapsed', true);
    fixture.detectChanges();
    expect(fixture.nativeElement.classList).toContain('collapsed');
  });
});
