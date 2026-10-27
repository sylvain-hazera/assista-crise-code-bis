import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subscription, forkJoin } from 'rxjs';

import { PointTypeService } from '../../services/point-type.service';
import { SiteSensibleService } from '../../services/site-sensible.service';
import { PointType } from '../../shared/models/point-operationnel.model';
import { pollWhileVisible } from '../../shared/utils/polling.util';
import {
  CategorieSiteSensible, SiteSensible, SourceSiteSensible, StatutSiteSensible,
  SyntheseSitesSensibles,
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
  recherche = '';

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
    { code: 'SOINS', libelle: 'Structure de soins ou médico-sociale' },
    { code: 'INDUSTRIE', libelle: 'Site industriel ou installation classée' },
    { code: 'ELEVAGE', libelle: "Élevage ou détention d'animaux" },
    { code: 'RASSEMBLEMENT', libelle: 'Équipement recevant du public' },
    { code: 'AUTRE', libelle: 'Autre' },
  ];

  constructor(
    private siteService: SiteSensibleService,
    private pointTypeService: PointTypeService,
  ) {}

  ngOnInit(): void {
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
      if (q && !`${site.nom} ${site.adresse || ''}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  compte(statut: StatutSiteSensible): number {
    return this.sites.filter(s => s.statut === statut).length;
  }

  importer(sources?: SourceSiteSensible[]): void {
    const demandees = sources ?? (this.synthese?.sources || []).map(s => s.code);
    if (!demandees.length) return;
    this.importEnCours = true;
    this.message = '';
    this.erreur = '';
    this.siteService.importer(demandees).subscribe({
      next: (reponse) => {
        this.importEnCours = false;
        const crees = Object.values(reponse.resultats)
          .reduce((total, r) => total + (r.crees || 0), 0);
        const attendues = Object.values(reponse.resultats).filter(r => r.asynchrone).length;
        this.message = crees
          ? `${crees} nouveau${crees > 1 ? 'x' : ''} site${crees > 1 ? 's' : ''} à vérifier.`
          : 'Aucun nouveau site : les sources ne connaissent rien de plus que ce que vous avez déjà.';
        if (attendues) {
          this.message += " La recherche FINESS continue en arrière-plan.";
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
    return mentions.slice(0, 3);
  }

  lienCarte(site: SiteSensible): string | null {
    if (site.latitude == null || site.longitude == null) return null;
    return `https://www.openstreetmap.org/?mlat=${site.latitude}&mlon=${site.longitude}#map=18/${site.latitude}/${site.longitude}`;
  }
}
