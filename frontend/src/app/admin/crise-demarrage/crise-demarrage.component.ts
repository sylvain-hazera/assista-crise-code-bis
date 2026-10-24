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
import { AffectationCompetenceService } from '../../services/affectation-competence.service';
import { RoleOperationnelService } from '../../services/role-operationnel.service';
import { BesoinService } from '../../services/besoin.service';
import { CompetenceService } from '../../services/competence.service';
import { UserService } from '../../services/user.service';
import { NotificationAlertePCSService } from '../../services/notification-alerte-pcs.service';
import { NotificationAlertePCS } from '../../shared/models/notification-alerte-pcs.model';
import { Crisis } from '../../shared/models/crisis.model';
import { PointOperationnel, PointType } from '../../shared/models/point-operationnel.model';
import { Team } from '../../shared/models/team.model';
import { RoleOperationnel } from '../../shared/models/institution.model';
import { Besoin } from '../../shared/models/besoin.model';
import { Competence } from '../../shared/models/competence.model';
import { User } from '../../shared/models/user.model';

interface EtapePoint {
  // null tant que le type n'est pas choisi (lignes ajoutées par ajouterPoint()).
  pointTypeCode: string | null;
  titre: string;
  description: string;
  suggestions: string[];
  // Distingue les 3 lignes par défaut d'une ligne ajoutée (type + nom seulement).
  isDefault: boolean;
  nom: string;
  cree: boolean;
  point: PointOperationnel | null;
  equipeId: string | null;
  nouvelleEquipeNom: string;
  // Saisi au récapitulatif pour une équipe juste créée ; zone déduite du territoire de la crise.
  responsable: { prenom: string; nom: string; email: string; telephone: string; roleCode: string | null; membreExistantId: string | null };
  membresAjoutes: string[];
  themeIds: string[];
  competenceIds: string[];
  missionDescription: string;
  infosSaving: boolean;
  infosDone: boolean;
  infosSkipped: boolean;
  infosError: string;
  // Candidats résolus depuis l'institution réelle de l'équipe (voir chargerContexteEquipe).
  candidateMembers: User[];
}

/** Assistant de démarrage de crise : points stratégiques, équipes, récapitulatif.
 * Simple index `step` et panneaux conditionnels ; uniquement des endpoints existants
 * (PointOperationnelViewSet, TeamViewSet). Voir DOCUMENTATION.md, § 6.2. */
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
  // Territoire communal de la crise (pas de l'institution pilote), zone par défaut des équipes créées ici.
  criseCommuneCode: string | null = null;

  step = 1; // 1 = points, 2 = équipes, 3 = récapitulatif
  saving = false;
  errorMessage = '';

  savingPlan = false;
  planSaved = false;
  planErrorMessage = '';

  private extrasEtape(): Pick<EtapePoint,
    'responsable' | 'membresAjoutes' | 'themeIds' | 'competenceIds' | 'missionDescription' |
    'infosSaving' | 'infosDone' | 'infosSkipped' | 'infosError' | 'candidateMembers'
  > {
    return {
      responsable: { prenom: '', nom: '', email: '', telephone: '', roleCode: null, membreExistantId: null },
      membresAjoutes: [], themeIds: [], competenceIds: [], missionDescription: '',
      infosSaving: false, infosDone: false, infosSkipped: false, infosError: '',
      candidateMembers: [],
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
    private affectationCompetenceService: AffectationCompetenceService,
    private planService: PlanService,
    private roleOperationnelService: RoleOperationnelService,
    private besoinService: BesoinService,
    private competenceService: CompetenceService,
    private userService: UserService,
    private notificationAlertePCSService: NotificationAlertePCSService,
  ) {}

  ngOnInit(): void {
    this.criseId = this.route.snapshot.paramMap.get('id')!;
    this.crisisService.getById(this.criseId).subscribe(c => {
      this.crise = c;
      if (!this.messagePCS) {
        this.messagePCS = `La crise « ${c.name} » vient d'être déclarée, ce qui active le plan `
          + `communal/intercommunal de sauvegarde. Merci de prendre contact avec la cellule de crise.`;
      }
    });
    this.crisisService.getCommune(this.criseId).subscribe({
      next: (res) => (this.criseCommuneCode = res.commune_code),
      error: () => {},
    });
    this.pointTypeService.getAll().subscribe(types => (this.pointTypes = types));
    this.teamService.equipesInstitution().subscribe(teams => (this.teams = teams));
    this.roleOperationnelService.getAll().subscribe(roles => (this.roles = roles));
    this.besoinService.getAll().subscribe(besoins => (this.besoins = besoins));
    this.competenceService.getAll().subscribe(competences => (this.competences = competences));
    this.chargerNotificationsPCS();
  }

  // ══ Checklist d'alerte PCS/PICS (interlocuteurs à prévenir) ═══════════════
  notificationsPCS: NotificationAlertePCS[] = [];
  messagePCS = '';
  selectionEnvoiPCS = new Set<string>();
  envoiPCSEnCours = false;
  erreurEnvoiPCS = '';

  private chargerNotificationsPCS(): void {
    this.notificationAlertePCSService.getForCrise(this.criseId).subscribe(notifs => {
      this.notificationsPCS = notifs;
      // Lignes envoyables (non terminales) cochées par défaut.
      this.selectionEnvoiPCS = new Set(this.notificationsAutoEnAttente.map(n => n.id));
    });
  }

  get notificationsAuto(): NotificationAlertePCS[] {
    return this.notificationsPCS.filter(n => n.canal_tente === 'EMAIL' || n.canal_tente === 'MATRIX');
  }

  get notificationsAutoEnAttente(): NotificationAlertePCS[] {
    return this.notificationsAuto.filter(n => n.statut === 'EN_ATTENTE' || n.statut === 'ECHEC_AUTO');
  }

  get notificationsManuelles(): NotificationAlertePCS[] {
    return this.notificationsPCS.filter(n => n.canal_tente !== 'EMAIL' && n.canal_tente !== 'MATRIX');
  }

  toggleSelectionEnvoiPCS(id: string): void {
    if (this.selectionEnvoiPCS.has(id)) this.selectionEnvoiPCS.delete(id);
    else this.selectionEnvoiPCS.add(id);
  }

  envoyerSelectionPCS(): void {
    if (this.selectionEnvoiPCS.size === 0 || !this.messagePCS.trim()) return;
    this.envoiPCSEnCours = true;
    this.erreurEnvoiPCS = '';
    this.notificationAlertePCSService.envoyerLot(this.criseId, Array.from(this.selectionEnvoiPCS), this.messagePCS.trim()).subscribe({
      next: () => {
        this.envoiPCSEnCours = false;
        this.chargerNotificationsPCS();
      },
      error: () => {
        this.envoiPCSEnCours = false;
        this.erreurEnvoiPCS = "Échec de l'envoi — réessayez.";
      },
    });
  }

  confirmerNotificationPCS(notif: NotificationAlertePCS): void {
    this.notificationAlertePCSService.confirmer(notif.id).subscribe(updated => {
      this.notificationsPCS = this.notificationsPCS.map(n => (n.id === updated.id ? updated : n));
    });
  }

  libelleStatutPCS(statut: string): string {
    return {
      EN_ATTENTE: 'En attente', ENVOYE_AUTO: 'Envoyé', ECHEC_AUTO: "Échec d'envoi",
      CONFIRME_PAR_CONTACT: 'Confirmé par le contact', CONFIRME_MANUEL: 'Confirmé (manuel)',
    }[statut] || statut;
  }

  classeStatutPCS(statut: string): string {
    return {
      EN_ATTENTE: 'statut-attente', ENVOYE_AUTO: 'statut-envoye', ECHEC_AUTO: 'statut-echec',
      CONFIRME_PAR_CONTACT: 'statut-confirme', CONFIRME_MANUEL: 'statut-confirme',
    }[statut] || '';
  }

  libelleReponseContactPCS(notif: NotificationAlertePCS): string {
    if (!notif.reponse_contact) return '';
    return {
      PAS_DE_RAPPEL: 'Pas besoin de rappeler', MERCI_RAPPELER: 'Merci de rappeler', AUTRE: 'Autre',
    }[notif.reponse_contact] || '';
  }

  /** Relit l'institution via l'équipe elle-même, jamais l'institution en cache : un compte
   * multi-institutions résoudrait sinon la mauvaise liste. */
  private chargerContexteEquipe(etape: EtapePoint): void {
    if (!etape.equipeId) { return; }
    this.teamService.getById(etape.equipeId).subscribe(team => {
      if (!team.institution) { return; }
      this.userService.getAll({ institution: [team.institution] }).subscribe(users => {
        etape.candidateMembers = users;
      });
    });
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

  /** Crée en un lot les points nommés (case vide = non pourvu). */
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

  get etapesAvecPoint(): EtapePoint[] {
    return this.etapes.filter(e => e.cree && e.point);
  }

  /** Passe par `nouvelle_equipe_nom` sur le point, comme point-modal : implication de
   * l'institution, notification du référent, journalisation (_creer_equipe_pour_point). */
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
        // Lier un point n'ajoute pas la crise à Team.assigned_crises : appel explicite nécessaire.
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
            if (nomNouvelleEquipe) { this.chargerContexteEquipe(etape); }
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

  /** Spécialité et mission sont EXIGÉES ici (décision du 24/10/2026) : sans au moins une
   * compétence, aucune affectation de compétence n'est créée sur la crise et plus rien ne peut
   * être suggéré automatiquement ensuite ; sans mission, l'équipe n'a rien à quoi rattacher ses
   * ressources ni ses bénévoles recrutés. Une équipe laissée incomplète ici est une équipe qui
   * ne servira à rien le jour où la crise démarre. */
  equipeIncomplete(etape: EtapePoint): boolean {
    return etape.competenceIds.length === 0 || !etape.missionDescription.trim();
  }

  /** Complète l'équipe juste créée (contact, thèmes, spécialité, mission) pour que les
   * automatisations (hébergement, recrutement) fonctionnent ; zone déduite du territoire de la crise. */
  enregistrerEquipe(etape: EtapePoint): void {
    if (!etape.equipeId) { return; }
    if (this.equipeIncomplete(etape)) {
      etape.infosError = "Indiquez au moins une spécialité et la mission confiée : "
        + "sans elles, aucune demande ne pourra être suggérée automatiquement à cette équipe.";
      return;
    }
    const r = etape.responsable;
    const invite = !!(r.prenom.trim() && r.nom.trim() && r.email.trim() && r.roleCode);

    etape.infosSaving = true;
    etape.infosError = '';

    const patchPayload: Partial<Team> = {
      theme_ids: etape.themeIds,
      competence_ids: etape.competenceIds,
      communes: this.criseCommuneCode ? [this.criseCommuneCode] : [],
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
    appels.push(this.teamService.definirMission(etape.equipeId, etape.missionDescription.trim(), this.criseId));

    // Ce qui rend l'affectation automatique possible : `competence_ids` ci-dessus ne remplit que
    // les compétences de la FICHE équipe, que le moteur de suggestion ne regarde pas. Seule une
    // AffectationCompetence (équipe ↔ compétence ↔ crise) est lue par
    // meilleure_equipe_pour_competence. Sans ces appels, on créait des équipes avec leurs
    // spécialités et aucune demande ne leur était jamais suggérée.
    for (const competenceId of etape.competenceIds) {
      appels.push(this.affectationCompetenceService.create({
        crise: this.criseId, competence: competenceId, equipe: etape.equipeId, active: true,
      }));
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

  /** Même si l'utilisateur reporte, la zone d'intervention est fixée. */
  passerEquipe(etape: EtapePoint): void {
    etape.infosSkipped = true;
    if (etape.equipeId && this.criseCommuneCode) {
      this.teamService.patch(etape.equipeId, { communes: [this.criseCommuneCode] }).subscribe({ error: () => {} });
    }
  }

  /** Enregistre équipes et points comme Plan (références, pas de copie), réactivable sur une
   * prochaine crise via PlanViewSet.activer. */
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
        this.planErrorMessage = "Impossible d'enregistrer ce dispositif. Réessayez depuis la page Mon plan de sauvegarde.";
      },
    });
  }
}
