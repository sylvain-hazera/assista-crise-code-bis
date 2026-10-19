import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CanActivateFn, provideRouter } from '@angular/router';

import { AdminSidebarComponent } from './admin-sidebar.component';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { NAV_ITEMS } from '../admin-nav.config';
import { ADMIN_ROUTES } from '../../../admin/admin.routes';
import {
  accountValidationGuard, institutionalEffectiveGuard, sysAdminGuard, vulnerabilitesGuard, zonesGuard,
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

  it('un compte non institutionnel ne voit que « Mes interventions »', () => {
    const visibles = NAV_ITEMS.filter(i => component.isNavItemVisible(i)).map(i => i.label);
    expect(visibles).toEqual(['Mes interventions']);
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
      'autorite-locale': zonesGuard,
      'registre-vulnerables': vulnerabilitesGuard,
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
