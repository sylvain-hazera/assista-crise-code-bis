import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, ParamMap, Router } from '@angular/router';
import { debounceTime, distinctUntilChanged, of, Subject, switchMap, catchError, takeUntil } from 'rxjs';
import {
  AuditLogService, AuditLogAdminEntry, AuditLogFilters, Critere, CritereCle, CRITERES_CLES,
  FicheTrouvee, filtresVersParams,
} from '../../services/audit-log.service';
import { CrisisService } from '../../services/crisis.service';
import { Crisis } from '../../shared/models/crisis.model';

interface ActionOption {
  code: string;
  libelle: string;
}

interface ChampCritere {
  cle: CritereCle;
  libelle: string;
  aide: string;
}

/** Page Main courante : registre de tout ce qui a été fait et consulté, avec des critères
 *  cumulables (inclure ET exclure sur chacun), le rattachement crise / fonctionnement général
 *  et la recherche d'une fiche précise pour savoir qui l'a vue (demande du 21/10/2026, voir
 *  backend core/main_courante.py et core/tracabilite.py). Les filtres sont recopiés dans
 *  l'adresse de la page : un lien partagé rouvre exactement la même recherche. */
@Component({
  selector: 'app-audit-logs',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './audit-logs.component.html',
  styleUrls: ['./audit-logs.component.scss'],
})
export class AuditLogsComponent implements OnInit, OnDestroy {
  private destroy$ = new Subject<void>();

  isLoading = false;
  isExporting = false;
  errorMessage = '';

  entries: AuditLogAdminEntry[] = [];
  totalCount = 0;
  /** Au-delà de 10 000 entrées le serveur arrête de compter (voir AuditLogPage.count_plafonne) :
   *  on affiche « plus de 10 000 entrées », jamais un chiffre inventé. */
  totalPlafonne = false;
  /** Vient de `next` renvoyé par le serveur, pas d'un calcul sur le total : seule façon fiable
   *  de savoir s'il existe une page suivante quand le total est plafonné. */
  hasNext = false;
  page = 1;
  readonly pageSize = 50;

  /** « Masquer les comptes système » coché par défaut : les ponts radio et satellites écrivent
   *  en continu et noieraient les actions humaines. */
  filtres: AuditLogFilters = { masquer_systeme: true, criteres: [] };

  // ── Saisie d'un critère ────────────────────────────────────────────────────────────────
  readonly champs: ChampCritere[] = [
    { cle: 'utilisateur', libelle: 'Utilisateur', aide: 'email ou nom (partiel accepté)' },
    { cle: 'ip', libelle: 'Adresse IP', aide: 'ex. 82.64.29.195 ou plage 192.168.0.0/16' },
    { cle: 'objet', libelle: 'Fiche précise', aide: 'titre, nom, téléphone, email ou identifiant' },
    { cle: 'crise', libelle: 'Crise', aide: '' },
    { cle: 'action', libelle: 'Action', aide: '' },
    { cle: 'objet_type', libelle: "Type d'objet", aide: 'ex. Offer, User, Crisis' },
    { cle: 'institution', libelle: 'Institution', aide: 'nom (partiel accepté)' },
    { cle: 'recherche', libelle: 'Terme recherché', aide: 'mot tapé dans une recherche' },
  ];
  champ: CritereCle = 'utilisateur';
  saisie = '';
  /** Fiche choisie dans les suggestions (critère « Fiche précise »). */
  ficheChoisie: FicheTrouvee | null = null;
  suggestions: FicheTrouvee[] = [];
  /** Recherche de fiches disponible : réservée au super-admin côté serveur (403 sinon). Sans
   *  elle, on peut toujours coller l'identifiant d'une fiche. */
  rechercheFichesDisponible = false;
  private saisieFiche$ = new Subject<string>();

  crises: Crisis[] = [];

  readonly perimetres = [
    { code: '', libelle: 'Tous' },
    { code: 'CRISE', libelle: 'Liées à une crise' },
    { code: 'MULTI', libelle: 'Plusieurs crises' },
    { code: 'GENERAL', libelle: 'Fonctionnement général' },
    { code: 'INCONNU', libelle: 'Non déterminable' },
  ];
  readonly expositions = [
    { code: '', libelle: 'Toutes' },
    { code: 'FICHE', libelle: 'Fiche ouverte' },
    { code: 'LISTE', libelle: 'Liste avec coordonnées' },
    { code: 'LISTE_SANS_COORDONNEES', libelle: 'Liste sans coordonnées' },
    { code: 'EXPORT', libelle: 'Export' },
  ];

  // Options fixes (le référentiel AuditAction ne change quasiment jamais, pas d'endpoint dédié).
  readonly actionOptions: ActionOption[] = [
    { code: 'CONNEXION', libelle: 'Connexion' },
    { code: 'DECONNEXION', libelle: 'Déconnexion' },
    { code: 'LECTURE', libelle: 'Consultation' },
    { code: 'CREATION', libelle: 'Création' },
    { code: 'MODIFICATION', libelle: 'Modification' },
    { code: 'SUPPRESSION', libelle: 'Suppression' },
    { code: 'DESACTIVATION', libelle: 'Désactivation' },
    { code: 'REACTIVATION', libelle: 'Réactivation' },
    { code: 'AFFECTATION', libelle: 'Affectation' },
    { code: 'CLOTURE', libelle: 'Clôture de dossier' },
    { code: 'DELEGATION_COMPETENCE', libelle: 'Délégation de compétence' },
    { code: 'PRISE_PERMANENCE', libelle: 'Prise de permanence' },
    { code: 'FIN_PERMANENCE', libelle: 'Fin de permanence' },
    { code: 'ACQUITTEMENT', libelle: 'Acquittement' },
    { code: 'TELECHARGEMENT', libelle: 'Téléchargement de document' },
    { code: 'ENVOI_EMAIL', libelle: "Envoi d'email" },
    { code: 'EXPORT', libelle: 'Export de données' },
    { code: 'JOURNAL_BORD', libelle: 'Écriture au journal de bord' },
    { code: 'IMPORT_LISTE', libelle: "Import d'une liste (CSV/XLS)" },
    // Sonde de connectivité des satellites, supervision (voir SondeView) : comptée comme
    // compte système, donc masquée par défaut.
    { code: 'VERIFICATION', libelle: 'Vérification de fonctionnement' },
  ];

  constructor(
    private auditLogService: AuditLogService,
    private crisisService: CrisisService,
    private route: ActivatedRoute,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.lireAdresse(this.route.snapshot.queryParamMap);

    this.crisisService.getAll().pipe(takeUntil(this.destroy$), catchError(() => of([] as Crisis[])))
      .subscribe(crises => {
        this.crises = crises;
        this.filtres.criteres.filter(c => c.cle === 'crise')
          .forEach(c => c.libelle = crises.find(cr => cr.id === c.valeur)?.name ?? c.libelle);
      });

    this.auditLogService.rechercherFiches('').pipe(takeUntil(this.destroy$)).subscribe({
      next: () => {
        this.rechercheFichesDisponible = true;
        this.nommerFichesDesCriteres();
      },
      error: () => { this.rechercheFichesDisponible = false; },
    });

    this.saisieFiche$.pipe(
      debounceTime(300), distinctUntilChanged(),
      switchMap(q => q.trim().length < 2 || !this.rechercheFichesDisponible
        ? of(null)
        : this.auditLogService.rechercherFiches(q).pipe(catchError(() => of(null)))),
      takeUntil(this.destroy$),
    ).subscribe(res => this.suggestions = res?.resultats ?? []);

    this.load();
  }

  ngOnDestroy(): void { this.destroy$.next(); this.destroy$.complete(); }

  get totalPages(): number {
    return Math.max(1, Math.ceil(this.totalCount / this.pageSize));
  }

  /** Séparateur de milliers français. Fait ici plutôt qu'avec le pipe `number` : aucune locale
   *  n'est enregistrée dans l'application (le pipe formaterait « 2,489,938»), et l'enregistrer
   *  globalement changerait l'affichage de toutes les autres pages. */
  nombreFr(valeur: number): string {
    return valeur.toLocaleString('fr-FR');
  }

  load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.auditLogService.browse(this.filtres, this.page, this.pageSize)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (result) => {
          this.entries = result.results;
          this.totalCount = result.count;
          this.totalPlafonne = !!result.count_plafonne;
          this.hasNext = result.next !== null;
          this.isLoading = false;
        },
        error: (err) => {
          // 400 : critère invalide (IP mal saisie...), le serveur dit lequel.
          const detail = err?.status === 400 && err.error ? Object.values(err.error).flat().join(' ') : '';
          this.errorMessage = detail || "Impossible de charger le registre — réservé aux administrateurs.";
          this.entries = [];
          this.isLoading = false;
        },
      });
  }

  /** Recharge depuis la première page et recopie les filtres dans l'adresse. */
  appliquer(): void {
    this.page = 1;
    this.ecrireAdresse();
    this.load();
  }

  resetFilters(): void {
    this.filtres = { masquer_systeme: true, criteres: [] };
    this.appliquer();
  }

  goToPage(page: number): void {
    // Borne haute volontairement tirée de hasNext et non de totalPages : ce dernier est plafonné
    // sur un gros registre, s'y fier empêcherait d'aller au-delà de la 200e page.
    if (page < 1 || (page > this.page && !this.hasNext)) return;
    this.page = page;
    this.ecrireAdresse();
    this.load();
  }

  // ── Critères ───────────────────────────────────────────────────────────────────────────

  get champCourant(): ChampCritere {
    return this.champs.find(c => c.cle === this.champ)!;
  }

  changerChamp(): void {
    this.saisie = '';
    this.ficheChoisie = null;
    this.suggestions = [];
  }

  surSaisie(): void {
    this.ficheChoisie = null;
    if (this.champ === 'objet') this.saisieFiche$.next(this.saisie);
  }

  choisirFiche(fiche: FicheTrouvee): void {
    this.ficheChoisie = fiche;
    this.saisie = `${fiche.type_libelle} — ${fiche.libelle}`;
    this.suggestions = [];
  }

  /** Bouton « Inclure » / « Exclure » de la barre de saisie. */
  ajouterSaisie(exclu: boolean): void {
    const brut = this.saisie.trim();
    let valeur = brut;
    let libelle = brut;
    if (this.champ === 'objet') {
      if (this.ficheChoisie) {
        valeur = this.ficheChoisie.id;
        libelle = `${this.ficheChoisie.type_libelle} — ${this.ficheChoisie.libelle}`;
      } else if (!this.estIdentifiant(brut)) {
        this.errorMessage = 'Choisissez une fiche dans la liste, ou collez son identifiant.';
        return;
      }
    } else if (this.champ === 'crise') {
      libelle = this.crises.find(c => c.id === brut)?.name ?? brut;
    } else if (this.champ === 'action') {
      libelle = this.actionOptions.find(a => a.code === brut)?.libelle ?? brut;
    }
    if (!valeur) return;
    this.errorMessage = '';
    this.ajouterCritere({ cle: this.champ, valeur, libelle, exclu });
    this.saisie = '';
    this.ficheChoisie = null;
    this.suggestions = [];
  }

  /** Boutons « + / − » d'une valeur du tableau : ne garder que / exclure cette valeur. */
  filtrerSur(cle: CritereCle, valeur: string | null, libelle: string | null, exclu: boolean): void {
    if (!valeur) return;
    this.ajouterCritere({ cle, valeur, libelle: libelle || valeur, exclu });
  }

  private ajouterCritere(critere: Critere): void {
    const existant = this.filtres.criteres.find(c => c.cle === critere.cle && c.valeur === critere.valeur);
    if (existant) {
      existant.exclu = critere.exclu;
    } else {
      this.filtres.criteres = [...this.filtres.criteres, critere];
    }
    this.appliquer();
  }

  basculer(critere: Critere): void {
    critere.exclu = !critere.exclu;
    this.appliquer();
  }

  retirer(critere: Critere): void {
    this.filtres.criteres = this.filtres.criteres.filter(c => c !== critere);
    this.appliquer();
  }

  libelleChamp(cle: CritereCle): string {
    return this.champs.find(c => c.cle === cle)?.libelle ?? cle;
  }

  /** Fiche suivie par un critère « Fiche précise » inclus : la page devient l'historique de
   *  cette fiche (qui l'a ouverte, vue dans une liste, exportée). */
  get ficheSuivie(): Critere | null {
    const fiches = this.filtres.criteres.filter(c => c.cle === 'objet' && !c.exclu);
    return fiches.length === 1 ? fiches[0] : null;
  }

  // ── Affichage ──────────────────────────────────────────────────────────────────────────

  actionLibelle(code: string | null): string {
    return this.actionOptions.find(o => o.code === code)?.libelle ?? (code ?? '—');
  }

  expositionLibelle(entry: AuditLogAdminEntry): string | null {
    switch (entry.exposition) {
      case 'FICHE': return 'Fiche ouverte';
      case 'LISTE': return `Liste avec coordonnées · ${this.nombreFr(entry.nb_objets)} fiche${entry.nb_objets > 1 ? 's' : ''}`;
      case 'LISTE_SANS_COORDONNEES': return `Liste sans coordonnées · ${this.nombreFr(entry.nb_objets)} fiche${entry.nb_objets > 1 ? 's' : ''}`;
      case 'EXPORT': return `Export · ${this.nombreFr(entry.nb_objets)} fiche${entry.nb_objets > 1 ? 's' : ''}`;
      default: return null;
    }
  }

  perimetreLibelle(entry: AuditLogAdminEntry): string {
    switch (entry.perimetre) {
      case 'CRISE': return entry.crise_nom ?? 'Crise';
      case 'MULTI': return 'Plusieurs crises';
      case 'GENERAL': return 'Général';
      default: return '—';
    }
  }

  rechercheTexte(entry: AuditLogAdminEntry): string | null {
    if (!entry.recherche) return null;
    return Object.entries(entry.recherche)
      .map(([cle, v]) => `${cle} = ${Array.isArray(v) ? v.join(', ') : v}`)
      .join(' · ');
  }

  exportCsv(): void {
    this.isExporting = true;
    this.auditLogService.exportCsv(this.filtres)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (blob) => {
          const url = window.URL.createObjectURL(blob);
          const a = document.createElement('a');
          const horodatage = new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');
          a.href = url;
          a.download = `main-courante-${horodatage}.csv`;
          a.click();
          window.URL.revokeObjectURL(url);
          this.isExporting = false;
        },
        error: () => {
          this.errorMessage = "Impossible d'exporter le registre.";
          this.isExporting = false;
        },
      });
  }

  // ── Adresse de la page ─────────────────────────────────────────────────────────────────

  private ecrireAdresse(): void {
    const params: Record<string, string | string[] | null> = { ...filtresVersParams(this.filtres) };
    // masquer_systeme absent de l'adresse = coché (valeur par défaut) ; décoché = 0 explicite.
    params['masquer_systeme'] = this.filtres.masquer_systeme ? null : '0';
    params['page'] = this.page > 1 ? String(this.page) : null;
    this.router.navigate([], { relativeTo: this.route, queryParams: params, replaceUrl: true });
  }

  private lireAdresse(p: ParamMap): void {
    const criteres: Critere[] = [];
    for (const cle of CRITERES_CLES) {
      for (const [nom, exclu] of [[cle, false], [`${cle}_exclu`, true]] as [string, boolean][]) {
        for (const valeur of p.getAll(nom)) {
          const libelle = cle === 'action' ? (this.actionOptions.find(a => a.code === valeur)?.libelle ?? valeur) : valeur;
          criteres.push({ cle, valeur, libelle, exclu });
        }
      }
    }
    this.filtres = {
      date_debut: p.get('date_debut') ?? undefined,
      date_fin: p.get('date_fin') ?? undefined,
      succes: p.get('succes') ?? undefined,
      perimetre: p.get('perimetre') ?? undefined,
      exposition: p.get('exposition') ?? undefined,
      masquer_systeme: p.get('masquer_systeme') !== '0',
      criteres,
    };
    this.page = Math.max(1, Number(p.get('page')) || 1);
  }

  /** Critères « Fiche précise » venus d'un lien : seul l'identifiant est dans l'adresse, on
   *  retrouve le libellé de la fiche pour la pastille. */
  private nommerFichesDesCriteres(): void {
    this.filtres.criteres.filter(c => c.cle === 'objet' && c.libelle === c.valeur).forEach(c => {
      this.auditLogService.rechercherFiches(c.valeur).pipe(takeUntil(this.destroy$)).subscribe(res => {
        const fiche = res.resultats[0];
        if (fiche) c.libelle = `${fiche.type_libelle} — ${fiche.libelle}`;
      });
    });
  }

  private estIdentifiant(valeur: string): boolean {
    return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(valeur);
  }
}
