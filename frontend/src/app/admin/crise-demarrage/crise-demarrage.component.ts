import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Observable, forkJoin } from 'rxjs';

import { CrisisService } from '../../services/crisis.service';
import { PlanService } from '../../services/plan.service';
import { PointOperationnelService } from '../../services/point-operationnel.service';
import { PointTypeService } from '../../services/point-type.service';
import { TeamService } from '../../services/team.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { InstitutionService } from '../../services/institution.service';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../auth/services/auth.service';
import { Crisis } from '../../shared/models/crisis.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Team } from '../../shared/models/team.model';
import { RoleOperationnel, Institution } from '../../shared/models/institution.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { User } from '../../shared/models/user.model';

interface EtapePoint {
  // null tant qu'un type n'a pas été choisi (uniquement possible pour une ligne ajoutée via
  // ajouterPoint() — les 3 lignes par défaut ont toujours le leur dès le départ).
  pointTypeCode: string | null;
  titre: string;
  description: string;
  suggestions: string[];
  // Distingue les 3 lignes proposées par défaut (titre/description/suggestions fixes) d'une
  // ligne ajoutée par l'utilisateur (juste un sélecteur de type + un nom) — voir demande
  // utilisateur du 2026-09-15 : autant de points que voulu, pas figé à 3.
  isDefault: boolean;
  nom: string;
  cree: boolean;
  point: PointOperationnel | null;
  equipeId: string | null;
  nouvelleEquipeNom: string;
  // Renseigné directement au récap pour une équipe tout juste créée — voir demandes
  // utilisateur du 2026-09-15 : "pas un lien vers l'équipe", tout se fait ici (contact,
  // thèmes, spécialité, mission), zone déduite en silence du territoire de l'institution.
  responsable: { prenom: string; nom: string; email: string; telephone: string; roleCode: string | null; membreExistantId: string | null };
  membresAjoutes: string[];
  themeIds: string[];
  competenceIds: string[];
  missionDescription: string;
  infosSaving: boolean;
  infosDone: boolean;
  infosSkipped: boolean;
  infosError: string;
}

/** Wizard proposé juste après la déclaration d'une crise (ou depuis son détail, plus tard) pour
 * poser rapidement ses éléments stratégiques — voir la demande utilisateur du 2026-09-10.
 * Premier composant "multi-étapes" du projet : pas de librairie de stepper, juste un index
 * `step` et des panneaux conditionnels, cohérent avec le reste du code. Réutilise entièrement
 * des endpoints déjà existants (PointOperationnelViewSet, TeamViewSet) — aucune route backend
 * dédiée. */
@Component({
  selector: 'app-crise-demarrage',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './crise-demarrage.component.html',
  styleUrl: './crise-demarrage.component.scss',
})
export class CriseDemarrageComponent implements OnInit {

  criseId!: string;
  crise: Crisis | null = null;
  pointTypes: PointType[] = [];
  teams: Team[] = [];
  roles: RoleOperationnel[] = [];
  besoins: Besoin[] = [];
  competences: Competence[] = [];
  candidateMembers: User[] = [];
  monInstitutionId: string | null = null;
  monInstitution: Institution | null = null;

  step = 1; // 1 = points, 2 = équipes, 3 = récapitulatif
  saving = false;
  errorMessage = '';

  savingPlan = false;
  planSaved = false;
  planErrorMessage = '';

  private extrasEtape(): Pick<EtapePoint,
    'responsable' | 'membresAjoutes' | 'themeIds' | 'competenceIds' | 'missionDescription' |
    'infosSaving' | 'infosDone' | 'infosSkipped' | 'infosError'
  > {
    return {
      responsable: { prenom: '', nom: '', email: '', telephone: '', roleCode: null, membreExistantId: null },
      membresAjoutes: [], themeIds: [], competenceIds: [], missionDescription: '',
      infosSaving: false, infosDone: false, infosSkipped: false, infosError: '',
    };
  }

  etapes: EtapePoint[] = [
    {
      pointTypeCode: 'CELLULE_CRISE', titre: 'Cellule de crise',
      description: "Le lieu depuis lequel la crise est pilotée.",
      suggestions: ['Mairie'], isDefault: true,
      nom: 'Mairie', cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
    {
      pointTypeCode: 'HEBERGEMENT', titre: 'Centre d\'accueil des populations',
      description: "Où les personnes évacuées ou sinistrées sont accueillies.",
      suggestions: ['Salle des fêtes'], isDefault: true,
      nom: 'Salle des fêtes', cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
    {
      pointTypeCode: 'REGROUPEMENT_MOYENS', titre: 'Centre de regroupement des moyens',
      description: "Où le matériel et les ressources mobilisées sont centralisés.",
      suggestions: ['Salle des fêtes', 'Centre technique municipal'], isDefault: true,
      nom: 'Salle des fêtes', cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
      ...this.extrasEtape(),
    },
  ];

  constructor(
    private route: ActivatedRoute,
    private router: Router,
    private crisisService: CrisisService,
    private pointService: PointOperationnelService,
    private pointTypeService: PointTypeService,
    private teamService: TeamService,
    private planService: PlanService,
    private roleOperationnelService: RoleOperationnelService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private institutionService: InstitutionService,
    private userService: UserService,
    private authService: AuthService,
  ) {}

  ngOnInit(): void {
    this.criseId = this.route.snapshot.paramMap.get('id')!;
    this.crisisService.getById(this.criseId).subscribe(c => (this.crise = c));
    this.pointTypeService.getAll().subscribe(types => (this.pointTypes = types));
    this.teamService.equipesInstitution().subscribe(teams => (this.teams = teams));
    this.roleOperationnelService.getAll().subscribe(roles => (this.roles = roles));
    this.besoinService.getAll().subscribe(besoins => (this.besoins = besoins));
    this.competenceService.getAll().subscribe(competences => (this.competences = competences));

    this.monInstitutionId = this.authService.getCurrentUser()?.institution_id ?? null;
    if (this.monInstitutionId) {
      this.institutionService.getById(this.monInstitutionId).subscribe(inst => (this.monInstitution = inst));
      this.userService.getAll({ institution: [this.monInstitutionId] }).subscribe(users => (this.candidateMembers = users));
    }
  }

  private typeIdFor(code: string): string | null {
    return this.pointTypes.find(t => t.code === code)?.id ?? null;
  }

  pointTypeLibelle(code: string | null): string {
    return this.pointTypes.find(t => t.code === code)?.libelle ?? '';
  }

  choisirSuggestion(etape: EtapePoint, nom: string): void {
    etape.nom = nom;
  }

  /** Autant de points stratégiques que voulu, pas figé aux 3 par défaut — voir demande
   * utilisateur du 2026-09-15. */
  ajouterPoint(): void {
    this.etapes = [
      ...this.etapes,
      {
        pointTypeCode: null, titre: 'Nouveau point', description: '', suggestions: [], isDefault: false,
        nom: '', cree: false, point: null, equipeId: null, nouvelleEquipeNom: '',
        ...this.extrasEtape(),
      },
    ];
  }

  retirerPoint(etape: EtapePoint): void {
    this.etapes = this.etapes.filter(e => e !== etape);
  }

  /** Crée en un lot tous les points dont le nom a été renseigné (une case vide = non pourvu,
   * plus besoin d'un bouton "passer" séparé maintenant que tout est sur un seul écran). */
  terminerEtapePoints(): void {
    const aCreer = this.etapes.filter(e => e.nom.trim());
    const sansType = aCreer.find(e => !e.pointTypeCode);
    if (sansType) {
      this.errorMessage = `Choisissez un type pour "${sansType.nom}".`;
      return;
    }
    this.errorMessage = '';
    if (aCreer.length === 0) {
      this.step = 2;
      return;
    }
    this.saving = true;
    let restant = aCreer.length;
    let echec = false;
    const fini = () => {
      restant--;
      if (restant === 0) {
        this.saving = false;
        if (echec) {
          this.errorMessage = "Certains points n'ont pas pu être créés — réessayez, ou retirez-les avant de continuer.";
        } else {
          this.step = 2;
        }
      }
    };
    aCreer.forEach(etape => {
      const typeId = this.typeIdFor(etape.pointTypeCode!);
      if (!typeId) { echec = true; fini(); return; }
      this.pointService.create({ nom: etape.nom.trim(), type: typeId, crise: this.criseId }).subscribe({
        next: (point) => { etape.cree = true; etape.point = point; fini(); },
        error: () => { echec = true; fini(); },
      });
    });
  }

  /** Points réellement créés à l'étape "équipes" (les lignes non renseignées n'y figurent pas). */
  get etapesAvecPoint(): EtapePoint[] {
    return this.etapes.filter(e => e.cree && e.point);
  }

  /** Un point n'a une équipe "complète" que si elle passe par le même mécanisme serveur que
   * partout ailleurs (point-modal, `nouvelle_equipe_nom` sur le create/update du point) : ça
   * déclare l'institution comme actrice de la crise (ImplicationInstitution), notifie son
   * référent et journalise le tout — un simple `TeamService.create({name})` fait ici avant ce
   * correctif ne faisait rien de tout ça (voir _creer_equipe_pour_point côté backend). */
  terminerEtapeEquipes(): void {
    const affectations = this.etapesAvecPoint.filter(e => e.point && (e.equipeId || e.nouvelleEquipeNom.trim()));
    if (affectations.length === 0) {
      this.step = 3;
      return;
    }
    this.saving = true;
    let restant = affectations.length;
    const equipesACrise = new Set<string>();
    const terminerSiFini = () => {
      restant--;
      if (restant === 0) {
        // Lier le point à l'équipe (ci-dessus) n'ajoute jamais la crise à
        // Team.assigned_crises — sans cet appel, l'équipe reste invisible dans les vues qui
        // s'appuient spécifiquement sur ce champ (ressources mobilisées, recrutement scopé,
        // matching hébergement), même si elle est bien affectée aux points de la crise.
        equipesACrise.forEach(equipeId => {
          this.teamService.assignerCrise(equipeId, this.criseId).subscribe({ error: () => {} });
        });
        this.saving = false;
        this.step = 3;
      }
    };
    affectations.forEach(etape => {
      const nomNouvelleEquipe = etape.nouvelleEquipeNom.trim();
      const payload = nomNouvelleEquipe && !etape.equipeId
        ? { nouvelle_equipe_nom: nomNouvelleEquipe }
        : { equipe: etape.equipeId };
      this.pointService.update(etape.point!.id, payload).subscribe({
        next: (updated) => {
          etape.point = updated;
          if (updated.equipe) {
            etape.equipeId = updated.equipe;
            equipesACrise.add(updated.equipe);
          }
          terminerSiFini();
        },
        error: () => terminerSiFini(),
      });
    });
  }

  terminer(): void {
    this.router.navigate(['/admin/crises']);
  }

  toggleThemeFor(etape: EtapePoint, id: string, checked: boolean): void {
    etape.themeIds = checked ? [...etape.themeIds, id] : etape.themeIds.filter(x => x !== id);
  }

  toggleCompetenceFor(etape: EtapePoint, id: string, checked: boolean): void {
    etape.competenceIds = checked ? [...etape.competenceIds, id] : etape.competenceIds.filter(x => x !== id);
  }

  /** Renseigne directement, sur une équipe tout juste créée par ce wizard, tout ce qui permet
   * aux mécanismes d'automatisation de la plateforme de fonctionner (matching hébergement,
   * recrutement scopé...) sans repasser par la fiche équipe — demande utilisateur du
   * 2026-09-15 : contact (existant ou invité), thèmes d'intervention, spécialité, mission
   * confiée, et la zone d'intervention déduite EN SILENCE du territoire de l'institution
   * (jamais demandée). Le point et la crise sont déjà affectés depuis terminerEtapeEquipes. */
  enregistrerEquipe(etape: EtapePoint): void {
    if (!etape.equipeId) { return; }
    const r = etape.responsable;
    const invite = !!(r.prenom.trim() && r.nom.trim() && r.email.trim() && r.roleCode);

    etape.infosSaving = true;
    etape.infosError = '';

    const patchPayload: Partial<Team> = {
      theme_ids: etape.themeIds,
      competence_ids: etape.competenceIds,
      communes: this.monInstitution?.commune_code ? [this.monInstitution.commune_code] : [],
    };
    if (r.membreExistantId) {
      patchPayload.member_ids = [...etape.membresAjoutes, r.membreExistantId];
    }

    const appels: Observable<any>[] = [this.teamService.patch(etape.equipeId, patchPayload)];
    if (invite) {
      appels.push(this.teamService.inviterMembre(etape.equipeId, {
        first_name: r.prenom.trim(), last_name: r.nom.trim(),
        email: r.email.trim(), phone_number: r.telephone.trim(), role_code: r.roleCode!,
      }));
    }
    if (etape.missionDescription.trim()) {
      appels.push(this.teamService.definirMission(etape.equipeId, etape.missionDescription.trim(), this.criseId));
    }

    forkJoin(appels).subscribe({
      next: () => {
        if (r.membreExistantId) { etape.membresAjoutes = [...etape.membresAjoutes, r.membreExistantId]; }
        etape.infosSaving = false;
        etape.infosDone = true;
      },
      error: () => {
        etape.infosSaving = false;
        etape.infosError = "Certaines informations n'ont pas pu être enregistrées. Réessayez, ou complétez plus tard depuis la fiche équipe.";
      },
    });
  }

  /** Même en repoussant à plus tard, la zone d'intervention est fixée en silence — c'est elle
   * qui permet aux automatisations de fonctionner dès maintenant, pas la peine d'attendre que
   * l'utilisateur revienne compléter la fiche équipe pour ça. */
  passerEquipe(etape: EtapePoint): void {
    etape.infosSkipped = true;
    if (etape.equipeId && this.monInstitution?.commune_code) {
      this.teamService.patch(etape.equipeId, { communes: [this.monInstitution.commune_code] }).subscribe({ error: () => {} });
    }
  }

  /** Réutilise Plan (dispositif pré-enregistré) tel quel : on référence les équipes/points déjà
   * créés (jamais de copie, voir docstring de Plan côté backend) sous un nom, pour pouvoir tout
   * ré-activer en un geste sur une prochaine crise via PlanViewSet.activer. Les équipes gardent
   * leur zone/compétences propres, le matériel reste attaché aux points eux-mêmes : rien à
   * dupliquer, il suffit de les regrouper ici. */
  enregistrerCommeDispositif(): void {
    const points = this.etapesAvecPoint;
    if (points.length === 0) {
      return;
    }
    const nomParDefaut = `Dispositif${this.crise?.name ? ' — ' + this.crise.name : ''}`;
    const nom = prompt('Nom du dispositif à sauvegarder pour la prochaine fois :', nomParDefaut);
    if (!nom || !nom.trim()) {
      return;
    }

    const pointsIds = points.map(e => e.point!.id);
    const equipesIds = [...new Set(points.map(e => e.equipeId).filter((id): id is string => !!id))];

    this.savingPlan = true;
    this.planErrorMessage = '';
    this.planService.create({ nom: nom.trim(), points_ids: pointsIds, equipes_ids: equipesIds }).subscribe({
      next: () => {
        this.savingPlan = false;
        this.planSaved = true;
      },
      error: () => {
        this.savingPlan = false;
        this.planErrorMessage = "Impossible d'enregistrer ce dispositif. Réessayez depuis la page Plans.";
      },
    });
  }
}
