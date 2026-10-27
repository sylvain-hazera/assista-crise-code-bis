import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription, forkJoin } from 'rxjs';

import { PointTypeService } from '../../services/point-type.service';
import { SiteSensibleService } from '../../services/site-sensible.service';
import { PointType } from '../../shared/models/point-operationnel.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import {
  CategorieSiteSensible, CoordonneesDevoilees, SiteSensible, SourceSiteSensible,
  StatutSiteSensible, SyntheseSitesSensibles,
} from '../../shared/models/site-sensible.model';

/**
 * Inventaire des enjeux du territoire pour le plan de sauvegarde communal : écoles, structures
 * de soins, sites industriels, équipements recevant du public.
 *
 * La page assume une posture, et son texte le dit à l'agent : les bases publiques REMPLISSENT le
 * formulaire, elles ne signent pas le plan. Tout arrive en « à vérifier », rien n'est compté
 * comme retenu avant qu'un agent l'ait dit. C'est volontaire : FINESS garde des pharmacies
 * fermées depuis 2009, et le recensement des équipements sportifs classe les écluses du canal de
 * Nantes à Brest en « installation sportive ». Présenter ça comme établi produirait un plan faux
 * avec l'autorité de l'État derrière.
 *
 * « À vérifier » ne veut pas dire « à écarter » : les élevages, par exemple, ont leur catégorie
 * et leur effectif animal affiché, parce que la protection des animaux est une mission du plan
 * — un cheptel s'évacue, s'abreuve et se ventile, et ça se prépare avant.
 */
@Component({
  selector: 'app-sites-sensibles',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './sites-sensibles.component.html',
  styleUrl: './sites-sensibles.component.scss',
})
export class SitesSensiblesComponent implements OnInit, OnDestroy {
  sites: SiteSensible[] = [];
  synthese: SyntheseSitesSensibles | null = null;
  pointTypes: PointType[] = [];

  chargement = true;
  importEnCours = false;
  message = '';
  erreur = '';

  filtreCategorie = '';
  filtreStatut: StatutSiteSensible | '' = 'PROPOSE';
  /** « Qui est menacé » et « avec quoi j'agis » sont deux questions distinctes en crise. */
  filtreRole: '' | 'enjeu' | 'ressource' = '';
  recherche = '';

  /** Panneau de recensement SIRENE, et les thèmes cochés (remplis dans ngOnInit : THEMES_SIRENE
   * est déclaré plus bas et n'existe pas encore à l'initialisation de ce champ). */
  sirenOuvert = false;
  themesChoisis = new Set<CategorieSiteSensible>();

  /** Adresses dévoilées pendant cette visite, par identifiant de site. Rien n'est conservé :
   * revenir sur la page redemande un dévoilement, donc une nouvelle trace. */
  adressesDevoilees: Record<string, CoordonneesDevoilees> = {};

  /** Site pour lequel le choix du type de point est ouvert, et le type choisi. */
  pointPourSite: string | null = null;
  typePointChoisi = '';
  capacitePoint: number | null = null;

  private suiviImport?: Subscription;

  /** Formulaire d'ajout manuel, pour ce qu'aucune base publique ne connaît (salle des fêtes,
   * camping, exploitation agricole). */
  ajoutOuvert = false;
  nouveauSite: { nom: string; categorie: CategorieSiteSensible; adresse: string;
                 effectif_estime: number | null } = this.nouveauSiteVide();

  readonly CATEGORIES: { code: CategorieSiteSensible; libelle: string }[] = [
    { code: 'ENSEIGNEMENT', libelle: "Établissement d'enseignement" },
    { code: 'PETITE_ENFANCE', libelle: "Accueil du jeune enfant" },
    { code: 'SOINS', libelle: 'Structure de soins ou médico-sociale' },
    { code: 'INDUSTRIE', libelle: 'Site industriel ou installation classée' },
    { code: 'ELEVAGE', libelle: "Élevage ou détention d'animaux" },
    { code: 'VETERINAIRE', libelle: 'Soins aux animaux' },
    { code: 'HEBERGEMENT', libelle: 'Hébergement (hôtel, camping, village vacances)' },
    { code: 'RASSEMBLEMENT', libelle: 'Équipement recevant du public' },
    { code: 'MOYENS', libelle: 'Moyens et travaux (transport, engins, bâchage)' },
    { code: 'APPROVISIONNEMENT', libelle: 'Approvisionnement (alimentation, carburant, repas)' },
    { code: 'FUNERAIRE', libelle: 'Opérateur funéraire' },
    { code: 'AUTRE', libelle: 'Autre' },
  ];

  /** Les thèmes que SIRENE sait recenser. Choix explicite et non bouton unique : 105
   * établissements à Châteauneuf pour ces thèmes, 3 409 à Bordeaux — une commune doit pouvoir
   * n'en demander qu'un. « Accueil du jeune enfant » part décoché : il ramène surtout des
   * assistantes maternelles, donc des noms de personnes à leur domicile. */
  readonly THEMES_SIRENE: { code: CategorieSiteSensible; libelle: string; aide: string;
                            coche: boolean }[] = [
    { code: 'ELEVAGE', libelle: 'Élevages', coche: true,
      aide: 'Y compris les exploitations sous les seuils ICPE, les plus nombreuses' },
    { code: 'MOYENS', libelle: 'Moyens et travaux', coche: true,
      aide: 'Cars, bétaillères, engins de terrassement, couvreurs' },
    { code: 'HEBERGEMENT', libelle: 'Hébergement', coche: true,
      aide: 'Hôtels, campings, villages vacances : des lits, et du monde à évacuer' },
    { code: 'APPROVISIONNEMENT', libelle: 'Approvisionnement', coche: true,
      aide: 'Commerces, boulangeries, carburants, restauration collective' },
    { code: 'VETERINAIRE', libelle: 'Vétérinaires', coche: true,
      aide: 'Pour la prise en charge des animaux' },
    { code: 'FUNERAIRE', libelle: 'Opérateurs funéraires', coche: true, aide: '' },
    { code: 'PETITE_ENFANCE', libelle: 'Accueil du jeune enfant', coche: false,
      aide: 'Surtout des assistantes maternelles : des personnes, à leur domicile' },
  ];

  /** Tranches d'effectif salarié de l'INSEE. Renseignées pour les seuls employeurs. */
  private readonly TRANCHES_EFFECTIF: Record<string, string> = {
    '00': '0 salarié', '01': '1 à 2 salariés', '02': '3 à 5 salariés', '03': '6 à 9 salariés',
    '11': '10 à 19 salariés', '12': '20 à 49 salariés', '21': '50 à 99 salariés',
    '22': '100 à 199 salariés', '31': '200 à 249 salariés', '32': '250 à 499 salariés',
    '41': '500 à 999 salariés', '42': '1 000 à 1 999 salariés', '51': '2 000 à 4 999 salariés',
    '52': '5 000 à 9 999 salariés', '53': '10 000 salariés et plus',
  };

  constructor(
    private siteService: SiteSensibleService,
    private pointTypeService: PointTypeService,
  ) {}

  ngOnInit(): void {
    this.THEMES_SIRENE.filter(t => t.coche).forEach(t => this.themesChoisis.add(t.code));
    this.charger();
  }

  ngOnDestroy(): void {
    this.arreterSuivi();
  }

  private nouveauSiteVide() {
    return { nom: '', categorie: 'AUTRE' as CategorieSiteSensible, adresse: '',
             effectif_estime: null };
  }

  private charger(): void {
    this.chargement = true;
    forkJoin({
      sites: this.siteService.getAll(),
      synthese: this.siteService.synthese(),
      types: this.pointTypeService.getAll(),
    }).subscribe({
      next: ({ sites, synthese, types }) => {
        this.sites = sites;
        this.synthese = synthese;
        this.pointTypes = types.filter(t => t.actif);
        this.chargement = false;
        // Un import FINESS lancé précédemment peut encore tourner : son état vit en base, pas
        // dans le navigateur, donc il est toujours là après un changement de page.
        if (this.finessEnCours) {
          this.surveillerImport();
        }
      },
      error: () => {
        this.erreur = "Impossible de charger les sites sensibles de votre collectivité.";
        this.chargement = false;
      },
    });
  }

  get finessEnCours(): boolean {
    return (this.synthese?.imports || []).some(i => i.statut === 'EN_COURS');
  }

  /** Rafraîchit la synthèse tant qu'un import de fond tourne (FINESS), puis s'arrête de
   * lui-même. Sondage volontairement lent : l'import prend une vingtaine de secondes et
   * l'agent n'attend pas devant l'écran — et suspendu quand l'onglet passe en arrière-plan
   * (pollWhileVisible). */
  private surveillerImport(): void {
    if (this.suiviImport) return;
    this.suiviImport = pollWhileVisible(() => this.siteService.synthese(), 10000).subscribe({
      next: (synthese) => {
        this.synthese = synthese;
        if (!this.finessEnCours) {
          this.arreterSuivi();
          this.rechargerSites();
        }
      },
      error: () => this.arreterSuivi(),
    });
  }

  private arreterSuivi(): void {
    this.suiviImport?.unsubscribe();
    this.suiviImport = undefined;
  }

  private rechargerSites(): void {
    this.siteService.getAll().subscribe(sites => this.sites = sites);
  }

  get sitesFiltres(): SiteSensible[] {
    const q = this.recherche.trim().toLowerCase();
    return this.sites.filter(site => {
      if (this.filtreCategorie && site.categorie !== this.filtreCategorie) return false;
      if (this.filtreStatut && site.statut !== this.filtreStatut) return false;
      if (this.filtreRole === 'enjeu' && !site.est_enjeu) return false;
      if (this.filtreRole === 'ressource' && !site.est_ressource) return false;
      // L'adresse d'une ligne masquée n'est pas dans le navigateur : la recherche ne porte que
      // sur ce qui est affiché, sans quoi elle promettrait ce qu'elle ne peut pas tenir.
      if (q && !`${site.nom} ${site.adresse || ''}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  compteRole(role: 'enjeu' | 'ressource'): number {
    return this.sites.filter(s => (role === 'enjeu' ? s.est_enjeu : s.est_ressource)).length;
  }

  compte(statut: StatutSiteSensible): number {
    return this.sites.filter(s => s.statut === statut).length;
  }

  /** Les quatre sources non thématiques. SIRENE est volontairement exclue du bouton principal :
   * elle se demande par thèmes (voir recenserSirene), sinon une grande ville reçoit plus d'un
   * millier de lignes à relire d'un seul clic. */
  private sourcesNonThematiques(): SourceSiteSensible[] {
    return (this.synthese?.sources || []).map(s => s.code).filter(code => code !== 'SIRENE');
  }

  basculerTheme(code: CategorieSiteSensible): void {
    if (this.themesChoisis.has(code)) this.themesChoisis.delete(code);
    else this.themesChoisis.add(code);
  }

  /** Recense les thèmes cochés via SIRENE. Part en tâche de fond, comme FINESS. */
  recenserSirene(): void {
    if (!this.themesChoisis.size) return;
    this.importer(['SIRENE'], Array.from(this.themesChoisis));
  }

  importer(sources?: SourceSiteSensible[], categories?: CategorieSiteSensible[]): void {
    const demandees = sources ?? this.sourcesNonThematiques();
    if (!demandees.length) return;
    this.importEnCours = true;
    this.message = '';
    this.erreur = '';
    this.siteService.importer(demandees, categories).subscribe({
      next: (reponse) => {
        this.importEnCours = false;
        const crees = Object.values(reponse.resultats)
          .reduce((total, r) => total + (r.crees || 0), 0);
        const attendues = Object.values(reponse.resultats).filter(r => r.asynchrone).length;
        this.message = crees
          ? `${crees} nouveau${crees > 1 ? 'x' : ''} site${crees > 1 ? 's' : ''} à vérifier.`
          : 'Aucun nouveau site : les sources ne connaissent rien de plus que ce que vous avez déjà.';
        if (attendues) {
          this.message += " La recherche continue en arrière-plan.";
        }
        this.charger();
      },
      error: (err) => {
        this.importEnCours = false;
        this.erreur = err?.error?.error || "L'import a échoué.";
      },
    });
  }

  statuer(site: SiteSensible, statut: StatutSiteSensible): void {
    this.siteService.update(site.id, { statut }).subscribe({
      next: (maj) => {
        this.sites = this.sites.map(s => (s.id === maj.id ? maj : s));
        this.rafraichirSynthese();
      },
      error: () => this.erreur = "Impossible d'enregistrer cette décision.",
    });
  }

  /** Enregistre une correction saisie dans la ligne (nom, adresse, effectif, commentaire). */
  enregistrerChamp(site: SiteSensible, champ: keyof SiteSensible, valeur: unknown): void {
    if (site[champ] === valeur) return;
    this.siteService.update(site.id, { [champ]: valeur } as Partial<SiteSensible>).subscribe({
      next: (maj) => this.sites = this.sites.map(s => (s.id === maj.id ? maj : s)),
      error: () => this.erreur = "Impossible d'enregistrer cette correction.",
    });
  }

  private rafraichirSynthese(): void {
    this.siteService.synthese().subscribe({
      next: (synthese) => this.synthese = synthese,
      error: () => undefined,
    });
  }

  /** Demande au serveur l'adresse d'une personne en nom propre. Chaque appel écrit une ligne
   * de main courante : c'est le prix, assumé, de pouvoir recenser des exploitants chez eux. */
  devoiler(site: SiteSensible): void {
    if (this.adressesDevoilees[site.id]) return;
    this.siteService.devoiler(site.id).subscribe({
      next: (coordonnees) => this.adressesDevoilees[site.id] = coordonnees,
      error: () => this.erreur = "Impossible d'obtenir cette adresse.",
    });
  }

  /** Ce qu'il faut afficher dans la colonne adresse : la valeur normale, la valeur dévoilée, ou
   * rien tant que le dévoilement n'a pas eu lieu. */
  adresseAffichee(site: SiteSensible): string | null {
    if (!site.adresse_masquee) return site.adresse;
    return this.adressesDevoilees[site.id]?.adresse ?? null;
  }

  /** Un PointOperationnel est public : on ne propose jamais d'y recopier le domicile d'une
   * personne. Le serveur refuse de toute façon, l'écran ne doit pas le promettre. */
  peutCreerPoint(site: SiteSensible): boolean {
    return site.statut === 'RETENU' && !site.point_operationnel && !site.personne_physique;
  }

  ouvrirCreationPoint(site: SiteSensible): void {
    this.pointPourSite = site.id;
    this.typePointChoisi = this.pointTypes[0]?.id || '';
    this.capacitePoint = null;
  }

  annulerCreationPoint(): void {
    this.pointPourSite = null;
  }

  creerPoint(site: SiteSensible): void {
    if (!this.typePointChoisi) return;
    this.siteService.creerPoint(site.id, {
      type: this.typePointChoisi, capacite_accueil: this.capacitePoint,
    }).subscribe({
      next: () => {
        this.pointPourSite = null;
        this.message = `« ${site.nom} » est devenu un point opérationnel, avec son adresse et ses coordonnées.`;
        this.rechargerSites();
      },
      error: (err) => this.erreur = err?.error?.error || "Impossible de créer le point.",
    });
  }

  ajouterSite(): void {
    const site = this.nouveauSite;
    if (!site.nom.trim()) return;
    this.siteService.create({
      nom: site.nom.trim(),
      categorie: site.categorie,
      adresse: site.adresse.trim() || null,
      effectif_estime: site.effectif_estime,
    }).subscribe({
      next: () => {
        this.nouveauSite = this.nouveauSiteVide();
        this.ajoutOuvert = false;
        this.message = 'Site ajouté.';
        this.charger();
      },
      error: () => this.erreur = "Impossible d'ajouter ce site.",
    });
  }

  supprimer(site: SiteSensible): void {
    if (!confirm(`Supprimer définitivement « ${site.nom} » de l'inventaire ?`)) return;
    this.siteService.delete(site.id).subscribe({
      next: () => {
        this.sites = this.sites.filter(s => s.id !== site.id);
        this.rafraichirSynthese();
      },
      error: () => this.erreur = 'Impossible de supprimer ce site.',
    });
  }

  /** Mention que la source impose (Licence Ouverte) et qui renseigne l'agent sur la fraîcheur. */
  provenance(site: SiteSensible): string {
    if (site.source === 'SAISIE') return 'Saisie manuelle';
    const date = site.date_source
      ? new Date(site.date_source).toLocaleDateString('fr-FR')
      : 'date inconnue';
    return `${site.source_libelle} — ${date}`;
  }

  /** Ce que contient un élevage, en clair : « 56 000 volailles », « 1 232 animaux-équivalents
   * porcs ». C'est l'effectif autorisé par la rubrique ICPE, le seul ordre de grandeur public —
   * et celui qui dit combien d'animaux seraient à déplacer, à abreuver ou à ventiler. */
  private mentionsCheptel(attrs: Record<string, unknown>): string[] {
    const cheptel = attrs['cheptel'];
    if (!Array.isArray(cheptel)) return [];
    const mentions = cheptel.map(ligne => {
      const entree = ligne as { espece?: string | null; quantite?: number | null;
                                unite?: string | null };
      const espece = entree.espece || 'animaux';
      if (entree.quantite == null) return espece;
      const nombre = entree.quantite.toLocaleString('fr-FR');
      // « Animaux-Eq » est l'unité réglementaire : un porc charcutier et une truie ne pèsent pas
      // le même animal-équivalent. Le dire évite de lire l'effectif comme un compte de bêtes.
      return (entree.unite || '').toLowerCase().startsWith('animaux')
        ? `${nombre} animaux-équivalents ${espece}`
        : `${nombre} ${espece}`;
    });
    // Un même bâtiment porte souvent deux rubriques (autorisation puis enregistrement) :
    // afficher « 50 000 volailles » deux fois ferait croire à 100 000 animaux.
    return [...new Set(mentions)];
  }

  /** Ce que la source dit de particulier sur ce site, en clair. Volontairement court : trois
   * mentions au plus, celles qui changent une décision d'évacuation. */
  particularites(site: SiteSensible): string[] {
    const attrs = site.attributs || {};
    const mentions: string[] = this.mentionsCheptel(attrs);
    const especes = attrs['especes'];
    if (!mentions.length && Array.isArray(especes) && especes.length) {
      mentions.push(especes.join(', '));
    }
    const seveso = attrs['statut_seveso'];
    if (typeof seveso === 'string' && seveso !== 'Non Seveso') mentions.push(seveso);
    if (attrs['ied'] === true) mentions.push('Directive IED');
    // Géorisques signale les sites en cessation : l'activité s'arrête, pas forcément la présence
    // d'animaux ou de stock pendant la remise en état.
    const etat = attrs['etat_activite'];
    if (typeof etat === 'string' && etat && etat !== 'En exploitation avec titre') {
      mentions.push(etat);
    }
    if (attrs['regime']) mentions.push(`Régime : ${attrs['regime']}`);
    if (attrs['hebergement'] === 1) mentions.push('Internat');
    if (attrs['restauration'] === 1) mentions.push('Restauration sur place');
    if (typeof attrs['statut'] === 'string') mentions.push(attrs['statut'] as string);
    const handi = attrs['acces_handicap'];
    if (Array.isArray(handi) && handi.length) mentions.push('Accès PMR');
    if (attrs['type_etablissement']) mentions.push(attrs['type_etablissement'] as string);
    // SIRENE : l'activité déclarée, et l'effectif salarié quand l'INSEE le renseigne (les seuls
    // employeurs). Le code NAF sert de repli, un libellé manquant valant mieux qu'un vide.
    const naf = attrs['naf_libelle'] || attrs['naf'];
    if (typeof naf === 'string') mentions.push(naf);
    const tranche = attrs['tranche_effectif'];
    if (typeof tranche === 'string' && this.TRANCHES_EFFECTIF[tranche]) {
      mentions.push(this.TRANCHES_EFFECTIF[tranche]);
    }
    return mentions.slice(0, 3);
  }

  lienCarte(site: SiteSensible): string | null {
    const devoilees = this.adressesDevoilees[site.id];
    const latitude = site.latitude ?? devoilees?.latitude ?? null;
    const longitude = site.longitude ?? devoilees?.longitude ?? null;
    if (latitude == null || longitude == null) return null;
    return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=18/${latitude}/${longitude}`;
  }
}
