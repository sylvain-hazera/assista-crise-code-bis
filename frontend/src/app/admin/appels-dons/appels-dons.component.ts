import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { ChoixDonComponent } from './choix-don.component';
import { AppelDonsService } from '../../services/appel-dons.service';
import { CrisisService } from '../../services/crisis.service';
import { StockService } from '../../services/stock.service';
import {
  AppelAuxDons, BesoinDon, EnvoiDon, FamilleCatalogueDon, FoyerSinistre, LABELS_ETAT_BESOIN, LABELS_PUBLIC_DON, LigneDon, PersonneFoyer, PORTEES_APPEL, PublicDon,
} from '../../shared/models/appel-dons.model';
import { Crisis } from '../../shared/models/crisis.model';
import { DepotStock } from '../../shared/models/stock.model';

type Onglet = 'autres' | 'miens' | 'foyers';
type BrouillonFoyer = { id?: string; nom: string; contact: string; adresse: string; commentaire: string; crise: string; personnes: PersonneFoyer[]; besoins: LigneDon[] };

/**
 * Appels aux dons. Trois vues : ce que les AUTRES institutions demandent (et où je peux
 * m'engager), MES appels, et les foyers sinistrés dont le besoin fait l'appel.
 *
 * La règle qui tient tout : chaque ligne a un reste à couvrir, qui baisse dès qu'une
 * institution s'engage. Une ligne couverte est fermée — on ne collecte pas ce qui est promis.
 */
@Component({
  selector: 'app-appels-dons',
  standalone: true,
  imports: [CommonModule, FormsModule, ChoixDonComponent],
  templateUrl: './appels-dons.component.html',
  styleUrl: './appels-dons.component.scss',
})
export class AppelsDonsComponent implements OnInit {
  readonly publics = LABELS_PUBLIC_DON;
  readonly etatsBesoin = LABELS_ETAT_BESOIN;
  readonly portees = PORTEES_APPEL;
  readonly listePublics = Object.keys(LABELS_PUBLIC_DON) as PublicDon[];

  onglet: Onglet = 'autres';
  catalogue: FamilleCatalogueDon[] = [];
  crises: Crisis[] = [];
  depots: DepotStock[] = [];
  appels: AppelAuxDons[] = [];
  /** L'appel ouvert à l'écran. */
  appel: AppelAuxDons | null = null;
  foyers: FoyerSinistre[] = [];
  erreur = '';
  message = '';
  envoi = false;

  /** Quantité saisie sur chaque ligne où je veux m'engager. */
  promesses: Record<string, number | null> = {};
  annonce: { date_expedition: string; arrivee_prevue: string; transporteur: string; contact: string } | null = null;
  /** Réception : quantité comptée par engagement. */
  reception: { envoi: EnvoiDon; comptes: Record<string, number>; depot: string } | null = null;
  nouvelAppel: { titre: string; description: string; crise: string; depot: string; portee_km: number | null; livraison_adresse: string; livraison_horaires: string;
                 contact_nom: string; contact_telephone: string; contact_email: string } | null = null;
  foyer: BrouillonFoyer | null = null;
  depotRemise = '';

  constructor(private dons: AppelDonsService, private crisisService: CrisisService, private stocks: StockService) {}

  ngOnInit(): void {
    this.dons.catalogue().subscribe({ next: (c) => this.catalogue = c.familles, error: () => {} });
    this.crisisService.getAll().subscribe({ next: (c) => this.crises = c.filter(x => x.is_open !== false), error: () => {} });
    this.stocks.etat().subscribe({ next: (e) => this.depots = e.depots.filter(d => d.actif && !d.point), error: () => {} });
    this.ouvrirOnglet('autres');
  }

  ouvrirOnglet(onglet: Onglet): void {
    this.onglet = onglet;
    this.appel = null;
    this.erreur = this.message = '';
    this.nouvelAppel = null;
    this.foyer = null;
    if (onglet === 'foyers') {
      this.dons.foyers().subscribe({ next: (f) => this.foyers = f, error: (e) => this.erreur = this.lire(e, 'Les foyers n’ont pas pu être lus.') });
    } else {
      this.dons.appels(onglet === 'miens').subscribe({ next: (a) => this.appels = a, error: (e) => this.erreur = this.lire(e, 'Les appels n’ont pas pu être lus.') });
    }
  }

  // ── Lecture d'un appel ──────────────────────────────────────────────────────────────────
  ouvrir(appel: AppelAuxDons): void { this.appel = appel; this.promesses = {}; this.annonce = null; this.reception = null; this.erreur = this.message = ''; }

  /** Les lignes de l'appel, regroupées par famille du catalogue. */
  get parFamille(): { libelle: string; lignes: BesoinDon[] }[] {
    const groupes = new Map<string, BesoinDon[]>();
    for (const besoin of this.appel?.besoins ?? []) groupes.set(besoin.famille, [...(groupes.get(besoin.famille) ?? []), besoin]);
    return [...groupes.entries()].map(([code, lignes]) => ({ libelle: this.catalogue.find(f => f.famille === code)?.libelle ?? 'Autre', lignes }));
  }

  get mesPromesses(): { id: string; libelle: string; quantite: number }[] {
    return (this.appel?.besoins ?? []).flatMap(b => b.engagements.filter(e => e.le_mien && e.statut === 'PROMIS')
      .map(e => ({ id: e.id, libelle: b.libelle, quantite: e.quantite })));
  }

  pourcent(a: AppelAuxDons): number {
    return a.avancement.pieces_voulues ? Math.round(100 * (a.avancement.pieces_voulues - a.avancement.pieces_restantes) / a.avancement.pieces_voulues) : 0;
  }

  private geste(geste: Parameters<AppelDonsService['geste']>[1], corps: Record<string, unknown>, succes: string, apres?: (a: AppelAuxDons) => void): void {
    if (!this.appel) return;
    this.envoi = true;
    this.erreur = this.message = '';
    this.dons.geste(this.appel.id, geste, corps).subscribe({
      next: (appel) => {
        this.envoi = false;
        this.appel = appel;
        this.appels = this.appels.map(a => a.id === appel.id ? appel : a);
        this.message = succes;
        apres?.(appel);
      },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce geste n’a pas abouti.'); },
    });
  }

  // ── Je m'engage, j'annonce mon envoi ────────────────────────────────────────────────────
  engager(besoin: BesoinDon): void {
    const quantite = this.promesses[besoin.id];
    if (!quantite || quantite < 1) return;
    this.geste('engager', { besoin: besoin.id, quantite }, `Engagement pris : ${quantite} × ${besoin.libelle}. Annoncez votre envoi sous ${this.appel!.delai_engagement_jours} jours, sinon cette part sera rendue aux autres.`,
      () => this.promesses[besoin.id] = null);
  }

  renoncer(engagement: string): void { this.geste('annuler-engagement', { engagement }, 'Engagement annulé : la part est rendue aux autres.'); }

  preparerAnnonce(): void { this.annonce = { date_expedition: new Date().toISOString().slice(0, 10), arrivee_prevue: '', transporteur: '', contact: '' }; }

  annoncer(): void {
    if (!this.annonce) return;
    this.geste('annoncer-envoi', { ...this.annonce, engagements: this.mesPromesses.map(p => p.id) }, 'Envoi annoncé : le destinataire le comptera à l’arrivée.',
      () => this.annonce = null);
  }

  // ── Mon appel ───────────────────────────────────────────────────────────────────────────
  preparerAppel(): void {
    this.erreur = this.message = '';
    this.nouvelAppel = { titre: '', description: '', crise: this.crises.length === 1 ? this.crises[0].id : '', depot: this.depots.length === 1 ? this.depots[0].id : '', portee_km: 100,
      livraison_adresse: '', livraison_horaires: '', contact_nom: '', contact_telephone: '', contact_email: '' };
  }

  creerAppel(): void {
    const n = this.nouvelAppel;
    if (!n || !n.titre.trim()) return;
    this.envoi = true;
    this.dons.enregistrerAppel({ ...n, crise: n.crise || null, depot: n.depot || null }).subscribe({
      next: (appel) => { this.envoi = false; this.nouvelAppel = null; this.appels = [appel, ...this.appels]; this.ouvrir(appel);
        this.message = 'Appel créé en brouillon. Ajoutez ses lignes, ou reprenez le besoin des foyers, puis ouvrez-le.'; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Cet appel n’a pas pu être créé.'); },
    });
  }

  /** Élargir (ou resserrer) le périmètre : on commence près du sinistre, on élargit si le besoin n'est pas couvert. */
  changerPortee(km: number | null): void {
    if (!this.appel || km === this.appel.portee_km) return;
    this.envoi = true;
    this.erreur = this.message = '';
    this.dons.enregistrerAppel({ id: this.appel.id, portee_km: km }).subscribe({
      next: (appel) => { this.envoi = false; this.appel = appel; this.appels = this.appels.map(a => a.id === appel.id ? appel : a);
        this.message = `L'appel est maintenant lancé ${appel.portee}.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Le périmètre n’a pas pu être changé.'); },
    });
  }

  ajouterLigne(ligne: LigneDon): void {
    // Une ligne ajoutée à la main vaut pour une personne (ou un foyer) de plus ; un mot personnel garde sa ligne à part.
    const deja = this.appel?.besoins.find(b => b.famille === ligne.famille && b.designation === ligne.designation && b.public === ligne.public
      && b.taille === ligne.taille && b.message === (ligne.message ?? ''));
    this.geste('lignes', { lignes: [{ ...ligne, quantite_voulue: (deja?.quantite_voulue ?? 0) + ligne.quantite,
      nb_beneficiaires: (deja?.nb_beneficiaires ?? 0) + 1 }] }, 'Ligne ajoutée.');
  }

  changerQuantite(besoin: BesoinDon, valeur: string): void {
    const quantite = Math.floor(+valeur);
    if (!(quantite >= 0) || quantite === besoin.quantite_voulue) return;
    this.geste('lignes', { lignes: [{ famille: besoin.famille, designation: besoin.designation, public: besoin.public, taille: besoin.taille,
      message: besoin.message, neuf_exige: besoin.neuf_exige, precision: besoin.precision, quantite_voulue: quantite }] }, quantite ? 'Quantité mise à jour.' : 'Ligne retirée.');
  }

  reprendreFoyers(): void {
    this.geste('reprendre-foyers', {}, '', (a) => this.message = `Besoin de ${a.reprise?.foyers ?? 0} foyer(s) repris : ${a.reprise?.lignes_creees ?? 0} ligne(s) ajoutée(s), ${a.reprise?.lignes_ajustees ?? 0} ajustée(s).`);
  }

  publier(): void { this.geste('ouvrir', {}, 'Appel ouvert : les autres institutions peuvent le consulter et s’y engager.'); }
  clore(): void { if (confirm('Clore cet appel ? Les promesses pas encore expédiées seront annulées.')) this.geste('clore', {}, 'Appel clos.'); }

  preparerReception(envoi: EnvoiDon): void {
    this.reception = { envoi, depot: this.appel?.depot ?? '', comptes: Object.fromEntries(envoi.lignes.map(l => [l.engagement, l.quantite])) };
  }

  recevoir(): void {
    const r = this.reception;
    if (!r) return;
    this.geste('recevoir-envoi', { envoi: r.envoi.id, comptes: r.comptes, ...(r.depot ? { depot: r.depot } : {}) }, '',
      (a) => { this.reception = null; this.message = a.entre_en_stock ? 'Réception enregistrée : les dons sont entrés en stock.' : 'Réception enregistrée (sans entrée en stock : aucun dépôt indiqué).'; });
  }

  // ── Foyers ──────────────────────────────────────────────────────────────────────────────
  nouveauFoyer(): void {
    this.erreur = this.message = '';
    this.foyer = { nom: '', contact: '', adresse: '', commentaire: '', crise: this.crises.length === 1 ? this.crises[0].id : '', personnes: [], besoins: [] };
  }

  modifierFoyer(f: FoyerSinistre): void {
    this.erreur = this.message = '';
    this.foyer = { id: f.id, nom: f.nom, contact: f.contact, adresse: f.adresse, commentaire: f.commentaire, crise: f.crise ?? '',
      personnes: f.personnes.map(p => ({ ...p })), besoins: f.besoins.map(b => ({ famille: b.famille, designation: b.designation, public: b.public,
        taille: b.taille, neuf_exige: b.neuf_exige, quantite: b.quantite, quantite_urgence: b.quantite_urgence, message: b.message ?? '' })) };
  }

  ajouterPersonne(): void { this.foyer?.personnes.push({ public: 'HOMME', age: null, taille_haut: '', taille_bas: '', pointure: '' }); }

  /** Grille de tailles d'une personne pour une mesure, lue dans le catalogue. */
  grille(personne: PersonneFoyer, mesure: 'haut' | 'pointure'): string[] {
    const articles = this.catalogue.find(f => f.famille === 'VETEMENTS')?.articles ?? [];
    return articles.find(a => a.mesure === mesure && a.publics.includes(personne.public))?.tailles[personne.public] ?? [];
  }

  /** Le trousseau proposé pour chaque personne, dans ses tailles : ajouté aux besoins du foyer, à ajuster ensuite. */
  proposerTrousseau(): void {
    const f = this.foyer;
    if (!f) return;
    for (const personne of f.personnes) {
      for (const famille of this.catalogue.filter(c => ['VETEMENTS', 'PUERICULTURE', 'SCOLAIRE'].includes(c.famille))) {
        for (const article of famille.articles.filter(a => a.publics.includes(personne.public))) {
          const taille = article.mesure === 'haut' ? personne.taille_haut : article.mesure === 'bas' ? (personne.taille_bas || personne.taille_haut)
            : article.mesure === 'pointure' ? personne.pointure : '';
          this.ajouterBesoin({ famille: famille.famille, designation: article.designation, public: personne.public, taille, neuf_exige: article.neuf_exige,
            quantite: article.quantite, quantite_urgence: article.quantite_urgence, message: '' });
        }
      }
    }
    this.message = 'Trousseau proposé : retirez ce qui n’est pas nécessaire, ajustez ce qu’il faut pour durer et ce qu’il faut tout de suite, puis enregistrez.';
  }

  ajouterBesoin(ligne: LigneDon): void {
    const f = this.foyer;
    if (!f) return;
    // Jamais de fusion : chaque ligne est le besoin d'UNE personne du foyer. Deux garçons en 8 ans font deux
    // lignes, et l'appel dira « pour 2 garçons ».
    f.besoins.push({ ...ligne, quantite_urgence: ligne.quantite_urgence ?? Math.max(1, Math.floor(ligne.quantite / 2)), message: ligne.message ?? '' });
  }

  libelle(ligne: LigneDon): string { return [ligne.designation, ligne.public ? this.publics[ligne.public].toLowerCase() : '', ligne.taille].filter(Boolean).join(', '); }

  enregistrerFoyer(): void {
    const f = this.foyer;
    if (!f || !f.nom.trim()) return;
    this.envoi = true;
    this.erreur = '';
    this.dons.enregistrerFoyer({ ...f, crise: f.crise || null, besoins: f.besoins.filter(b => b.quantite > 0) }).subscribe({
      next: (foyer) => { this.envoi = false; this.foyer = null; this.poserFoyer(foyer); this.message = `Foyer ${foyer.reference} enregistré.`; },
      error: (e) => { this.envoi = false; this.erreur = this.lire(e, 'Ce foyer n’a pas pu être enregistré.'); },
    });
  }

  remettre(foyer: FoyerSinistre, besoin: string, valeur: string): void {
    const quantite = Math.floor(+valeur);
    if (!(quantite >= 1)) return;
    this.erreur = this.message = '';
    this.dons.remettre(foyer.id, besoin, quantite, this.depotRemise || undefined).subscribe({
      next: (maj) => { this.poserFoyer(maj); this.message = `Remise notée pour le foyer ${maj.reference}.`; },
      error: (e) => this.erreur = this.lire(e, 'Cette remise n’a pas pu être notée.'),
    });
  }

  private poserFoyer(f: FoyerSinistre): void { this.foyers = this.foyers.some(x => x.id === f.id) ? this.foyers.map(x => x.id === f.id ? f : x) : [...this.foyers, f]; }

  private lire(e: any, defaut: string): string {
    const corps = e?.error;
    if (!corps || typeof corps !== 'object') return defaut;
    if (typeof corps.detail === 'string') return corps.detail;
    const premier = Object.values(corps)[0];
    return (Array.isArray(premier) ? premier[0] : premier) as string || defaut;
  }
}
