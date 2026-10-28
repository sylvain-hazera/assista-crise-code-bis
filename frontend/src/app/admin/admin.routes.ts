import { Routes } from '@angular/router';
import { sysAdminGuard, institutionalEffectiveGuard, accountValidationGuard, autoriteLocaleGuard, vulnerabilitesGuard, membresAssociationGuard } from '../core/guards/admin.guard';
import { AccesRefuseComponent } from './acces-refuse/acces-refuse.component';

export const ADMIN_ROUTES: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: 'acces-refuse', component: AccesRefuseComponent },

  // ── Toujours visibles ──
  { path: 'dashboard', loadComponent: () => import('./dashboard/dashboard.component').then(m => m.DashboardComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'cellule-crise', loadComponent: () => import('./cellule-crise/cellule-crise.component').then(m => m.CelluleCriseComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'vue-mairie', loadComponent: () => import('./vue-mairie/vue-mairie.component').then(m => m.VueMairieComponent), canActivate: [institutionalEffectiveGuard] },

  // ── Crise en cours ──
  { path: 'signalements', loadComponent: () => import('./reporting/reporting.component').then(m => m.ReportingComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'declarations-securite', loadComponent: () => import('./declarations-securite/declarations-securite.component').then(m => m.DeclarationsSecuriteComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'missions', loadComponent: () => import('./missions/missions.component').then(m => m.MissionsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'crises', loadComponent: () => import('./crises/crises.component').then(m => m.CrisesComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'crises/:crisisId/stocks', loadComponent: () => import('./stocks-comparaison/stocks-comparaison.component').then(m => m.StocksComparaisonComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'crises/:id/demarrage', loadComponent: () => import('./crise-demarrage/crise-demarrage.component').then(m => m.CriseDemarrageComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'centres', loadComponent: () => import('./centres/centres.component').then(m => m.CentresComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'ressources-mobilisees', loadComponent: () => import('./ressources-mobilisees/ressources-mobilisees.component').then(m => m.RessourcesMobiliseesComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'supervision-pc-crise', loadComponent: () => import('./supervision-pc-crise/supervision-pc-crise.component').then(m => m.SupervisionPcCriseComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'demandes-mobilisation', loadComponent: () => import('./demandes-mobilisation/demandes-mobilisation.component').then(m => m.DemandesMobilisationComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'affectations', loadComponent: () => import('./affectations/affectations.component').then(m => m.AffectationsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'dossiers', loadComponent: () => import('./dossiers/dossiers.component').then(m => m.DossiersComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes', loadComponent: () => import('../pages/recherches-personnes/recherches-personnes.component').then(m => m.RecherchesPersonnesComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes/new', loadComponent: () => import('../pages/recherche-personne-create/recherche-personne-create.component').then(m => m.RecherchePersonneCreateComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'recherches-personnes/:id', loadComponent: () => import('../pages/recherche-personne-detail/recherche-personne-detail.component').then(m => m.RecherchePersonneDetailComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'carte', loadComponent: () => import('../shared/components/common/map/map.component').then(m => m.MapComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'main-courante', loadComponent: () => import('./audit-logs/audit-logs.component').then(m => m.AuditLogsComponent), canActivate: [sysAdminGuard] },

  // ── Post-critique — gestion à long terme ──
  { path: 'logement-intervenants', loadComponent: () => import('./logement-intervenants/logement-intervenants.component').then(m => m.LogementIntervenantsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'resultats', loadComponent: () => import('./results/results.component').then(m => m.ResultsComponent), canActivate: [institutionalEffectiveGuard] },

  // ── Préparation ──
  { path: 'equipes', loadComponent: () => import('./teams/teams.component').then(m => m.TeamsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'zones', loadComponent: () => import('./zones/zones.component').then(m => m.ZonesComponent), canActivate: [institutionalEffectiveGuard, autoriteLocaleGuard] },
  { path: 'simulation-inondation', loadComponent: () => import('./simulation-inondation/simulation-inondation.component').then(m => m.SimulationInondationComponent), canActivate: [institutionalEffectiveGuard, autoriteLocaleGuard] },
  { path: 'plans', loadComponent: () => import('./plans/plans.component').then(m => m.PlansComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'sites-sensibles', loadComponent: () => import('./sites-sensibles/sites-sensibles.component').then(m => m.SitesSensiblesComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'competences', loadComponent: () => import('./competences/competences.component').then(m => m.CompetencesComponent), canActivate: [institutionalEffectiveGuard] },
  // Gestion des membres d'une association agréée de sécurité civile : annuaire, recrutement,
  // qualifications, disponibilités. Gardee par `acces_membres_association` (champ serveur) :
  // une institution non associative ne doit pas voir cette page. Se fermer d'elle-meme ne
  // suffisait pas -- une mairie la trouvait cassee plutot qu'absente.
  { path: 'membres-association', loadComponent: () => import('./membres-association/membres-association.component').then(m => m.MembresAssociationComponent), canActivate: [institutionalEffectiveGuard, membresAssociationGuard] },
  { path: 'personnes-vulnerables', loadComponent: () => import('./personnes-vulnerables/personnes-vulnerables.component').then(m => m.PersonnesVulnerablesComponent), canActivate: [institutionalEffectiveGuard, vulnerabilitesGuard] },
  // Designation nominative (art. R. 121-7 du CASF) : garde `autoriteLocaleGuard` et non
  // `vulnerabilitesGuard` -- designer n'est pas acceder. Un maire dont personne n'est encore
  // habilite, lui-meme compris, doit pouvoir ouvrir cette page : c'est la seule porte d'entree
  // du dispositif.
  { path: 'habilitations-registre', loadComponent: () => import('./habilitations-registre/habilitations-registre.component').then(m => m.HabilitationsRegistreComponent), canActivate: [institutionalEffectiveGuard, autoriteLocaleGuard] },

  // ── Communications / Radio ──
  { path: 'meshcore-companions', loadComponent: () => import('./meshcore-companions/meshcore-companions.component').then(m => m.MeshcoreCompanionsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'meshcore-canaux', loadComponent: () => import('./meshcore-canaux/meshcore-canaux.component').then(m => m.MeshcoreCanauxComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'meshtastic-companions', loadComponent: () => import('./meshtastic-companions/meshtastic-companions.component').then(m => m.MeshtasticCompanionsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'meshtastic-canaux', loadComponent: () => import('./meshtastic-canaux/meshtastic-canaux.component').then(m => m.MeshtasticCanauxComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'satellites', loadComponent: () => import('./satellites/satellites.component').then(m => m.SatellitesComponent), canActivate: [institutionalEffectiveGuard] },

  // ── Administration ──
  { path: 'institutions', loadComponent: () => import('./institutions/institutions.component').then(m => m.InstitutionsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'besoins', loadComponent: () => import('./besoins/besoins.component').then(m => m.BesoinsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'materiel', loadComponent: () => import('./materiel/materiel.component').then(m => m.MaterielComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'conflits-synchronisation', loadComponent: () => import('./conflits-synchronisation/conflits-synchronisation.component').then(m => m.ConflitsSynchronisationComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'correspondances', loadComponent: () => import('./besoins-competences/besoins-competences.component').then(m => m.BesoinsCompetencesComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'utilisateurs', loadComponent: () => import('./users/users.component').then(m => m.UsersComponent), canActivate: [sysAdminGuard] },
  { path: 'validations-comptes', loadComponent: () => import('./account-validations/account-validations.component').then(m => m.AccountValidationsComponent), canActivate: [accountValidationGuard] },
  { path: 'monitoring', loadComponent: () => import('./monitoring/monitoring.component').then(m => m.MonitoringComponent), canActivate: [sysAdminGuard] },
  // anciennes pages séparées (20/10), devenues des onglets de la supervision technique
  { path: 'supervision-waf', redirectTo: '/admin/monitoring?onglet=waf' },
  { path: 'fail2ban', redirectTo: '/admin/monitoring?onglet=fail2ban' },

  // ── Hors menu : imports (ouverts depuis les pages concernées) ──
  { path: 'import-personnel', loadComponent: () => import('./import-personnel/import-personnel.component').then(m => m.ImportPersonnelComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'import-institutions', loadComponent: () => import('./import-institutions/import-institutions.component').then(m => m.ImportInstitutionsComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'import-correspondants-pcs', loadComponent: () => import('./import-correspondants-pcs/import-correspondants-pcs.component').then(m => m.ImportCorrespondantsPCSComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'import-interlocuteurs-pcs', loadComponent: () => import('./import-interlocuteurs-pcs/import-interlocuteurs-pcs.component').then(m => m.ImportInterlocuteursPCSComponent), canActivate: [institutionalEffectiveGuard] },
  { path: 'import-materiel-point', loadComponent: () => import('./import-materiel-point/import-materiel-point.component').then(m => m.ImportMaterielPointComponent), canActivate: [institutionalEffectiveGuard] },
];

