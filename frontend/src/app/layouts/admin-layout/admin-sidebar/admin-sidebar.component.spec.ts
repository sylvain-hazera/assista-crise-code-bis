import { ComponentFixture, TestBed } from '@angular/core/testing';
import { CanActivateFn, provideRouter } from '@angular/router';

import { AdminSidebarComponent } from './admin-sidebar.component';
import { AuthService } from '../../../auth/services/auth.service';
import { UserRole } from '../../../shared/models/user.model';
import { GROUPES_NAV, NAV_ITEMS, SOUS_GROUPES_NAV } from '../admin-nav.config';
import { ADMIN_ROUTES } from '../../../admin/admin.routes';
import {
  accountValidationGuard, adminPlateformeGuard, institutionalEffectiveGuard, sysAdminGuard, vulnerabilitesGuard, autoriteLocaleGuard,
  membresAssociationGuard, revueDroitsGuard, campagnesGuard, radioGuard,
} from '../../../core/guards/admin.guard';

describe('AdminSidebarComponent', () => {
  let component: AdminSidebarComponent;
  let fixture: ComponentFixture<AdminSidebarComponent>;
  let auth: jasmine.SpyObj<AuthService>;

  const item = (label: string) => NAV_ITEMS.find(i => i.label === label)!;

  beforeEach(async () => {
    // Les replis enregistrés par un essai ne doivent pas déborder sur le suivant.
    localStorage.removeItem('admin-sidebar-groupes-ouverts');
    localStorage.removeItem('admin-sidebar-sous-groupes-ouverts');
    auth = jasmine.createSpyObj<AuthService>('AuthService', [
      'isSysAdmin', 'isAdminPlateforme', 'getEffectiveRole', 'isAutoriteLocaleCommunale', 'getCurrentUser', 'isInstitutionalEffective',
    ]);
    auth.isSysAdmin.and.returnValue(false);
    auth.isAdminPlateforme.and.returnValue(false);
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
    // Toutes pour la même raison : elles EXPLIQUENT ce qu'il faut pour s'en servir au lieu de
    // disparaître. « Accueil radio » dit comment obtenir la radio et permet de la demander ;
    // « Mes interventions » et « Hébergement » disent, quand le compte n'est dans aucune
    // équipe, pourquoi la page est vide et à qui s'adresser (demande du 12/11/2026). Les
    // masquer laisserait croire que ces fonctions n'existent pas.
    //
    // « Devenir passerelle » rejoint la liste le 13/11/2026, et c'est un arbitrage assumé :
    // c'est un écran d'URGENCE — brancher une radio en USB sur un poste où l'on ne peut rien
    // installer — qu'on ne doit pas avoir à chercher le jour où il sert. Il explique lui aussi
    // ce qui manque (« aucune radio ne vous est accessible, demandez à votre encadrement »),
    // donc il satisfait le critère ci-dessus. Le restreindre se fait en une ligne dans
    // admin-nav.config.ts si l'entrée s'avère du bruit pour les comptes citoyens.
    //
    // « Mon relevé d'heures » les rejoint le 17/11/2026 : un bénévole d'association est un
    // compte ordinaire, et c'est là qu'il déclare « je pars », « je rentre ». À qui n'est
    // membre d'aucune équipe engagée, la page dit pourquoi elle n'a rien à lui proposer.
    const visibles = NAV_ITEMS.filter(i => component.isNavItemVisible(i)).map(i => i.label);
    expect(visibles).toEqual([
      // Même liste ; depuis la revue du 19/11/2026, « Devenir passerelle » est rangé en tête
      // de la radio, juste après « Accueil radio », et non plus en haut du menu.
      'Mes interventions', "Mon relevé d'heures", 'Hébergement', 'Accueil radio', 'Devenir passerelle',
    ]);
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

  it("la supervision technique et les comptes MQTT ne sont au menu que de l'administrateur de la plateforme", () => {
    // 18/11/2026 : `sysadmin` accepte les quatre rôles institutionnels ; toutes les mairies
    // voyaient ces deux entrées et n'y lisaient qu'un refus.
    auth.isSysAdmin.and.returnValue(true);
    auth.getEffectiveRole.and.returnValue(UserRole.LOCAL_AUTH);
    expect(component.isNavItemVisible(item('Supervision technique'))).toBeFalse();
    expect(component.isNavItemVisible(item('Comptes MQTT'))).toBeFalse();
    auth.isAdminPlateforme.and.returnValue(true);
    expect(component.isNavItemVisible(item('Supervision technique'))).toBeTrue();
    expect(component.isNavItemVisible(item('Comptes MQTT'))).toBeTrue();
  });

  describe('alignement avec admin.routes.ts', () => {
    const gardeAttendue: Record<string, CanActivateFn> = {
      institutionnel: institutionalEffectiveGuard,
      sysadmin: sysAdminGuard,
      'admin-plateforme': adminPlateformeGuard,
      'validation-comptes': accountValidationGuard,
      'autorite-locale': autoriteLocaleGuard,
      'registre-vulnerables': vulnerabilitesGuard,
      'membres-association': membresAssociationGuard,
      'revue-droits': revueDroitsGuard,
      campagnes: campagnesGuard,
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

  describe('revue du menu (19/11/2026)', () => {
    it("chaque entrée a sa propre icône : menu réduit, on ne distingue qu'elles", () => {
      const vues = new Map<string, string>();
      const doublons: string[] = [];
      for (const i of NAV_ITEMS) {
        if (vues.has(i.icon)) doublons.push(`${i.icon} : ${vues.get(i.icon)} / ${i.label}`);
        else vues.set(i.icon, i.label);
      }
      expect(doublons).toEqual([]);
    });

    const situation = (crise: boolean, n = 0) => ({
      signalements: n, messages_a_relire: n, demandes_mobilisation: null, crise_ouverte: crise,
    });

    it('hors crise, « Préparer » passe devant « Crise en cours » et s\'ouvre', () => {
      component.appliquerSituation(situation(false));
      const ordre = component.groupesNav.map(g => g.id);
      expect(ordre.indexOf('preparation')).toBeLessThan(ordre.indexOf('crise'));
      expect(component.estGroupeOuvert('preparation')).toBeTrue();
      expect(component.estGroupeOuvert('crise')).toBeFalse();
      component.appliquerSituation(situation(true));
      const enCrise = component.groupesNav.map(g => g.id);
      expect(enCrise.indexOf('crise')).toBeLessThan(enCrise.indexOf('preparation'));
      expect(component.estGroupeOuvert('crise')).toBeTrue();
    });

    it('un choix de l\'utilisateur n\'est plus défait par la situation', () => {
      component.toggleGroupe('administration');
      component.appliquerSituation(situation(false));
      expect(component.estGroupeOuvert('administration')).toBeTrue();
    });

    it('les étapes de la crise sont dépliées par défaut, pas les protocoles radio', () => {
      expect(component.estSousGroupeOuvert('crise-recevoir')).toBeTrue();
      expect(component.estSousGroupeOuvert('prep-connaitre')).toBeTrue();
      expect(component.estSousGroupeOuvert('meshcore')).toBeFalse();
    });

    it('les compteurs vont sur leurs pages, et seulement là', () => {
      component.appliquerSituation(situation(true, 4));
      expect(component.compteurDe(item('Signalements'))).toBe(4);
      expect(component.compteurDe(item('Messages à relire'))).toBe(4);
      expect(component.compteurDe(item('Demandes de mobilisation'))).toBe(0);
      expect(component.compteurDe(item('Missions'))).toBe(0);
    });

    it("« Standard de crise » est le premier écran de « Recevoir », « Crises » le premier de « Comprendre »", () => {
      const premier = (sous: string) => NAV_ITEMS.find(i => i.sousGroupe === sous)!.label;
      expect(premier('crise-recevoir')).toBe('Standard de crise');
      expect(premier('crise-comprendre')).toBe('Crises');
      expect(item('Messages à relire').groupe).toBe('crise');
    });

    it("ouvre le cadre de la page affichée, sans refermer les autres", () => {
      component.groupesOuverts = { crise: true };
      component.sousGroupesOuverts = {};
      component.ouvrirLeCadreDe('/admin/pcs-fiches?x=1');
      expect(component.groupesOuverts['preparation']).toBeTrue();
      expect(component.groupesOuverts['crise']).toBeTrue();
      component.ouvrirLeCadreDe('/admin/meshtastic-canaux/12');
      expect(component.groupesOuverts['communications']).toBeTrue();
      expect(component.sousGroupesOuverts['meshtastic']).toBeTrue();
      component.ouvrirLeCadreDe('/admin/dashboard');
      expect(Object.keys(component.groupesOuverts).sort()).toEqual(['communications', 'crise', 'preparation']);
    });
  });
});
