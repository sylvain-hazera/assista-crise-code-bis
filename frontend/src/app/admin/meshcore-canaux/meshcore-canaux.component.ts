import { AfterViewChecked, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { CanalMeshCoreService } from '../../services/canal-meshcore.service';
import { MessageMeshService } from '../../services/message-mesh.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { ContactMeshCoreService } from '../../services/contact-meshcore.service';
import { CanalMeshCore, CanalMeshCoreDetecte, MessageCanalMeshCore, MessageMeshLog, StatutMessageMesh } from '../../shared/models/canal-meshcore.model';
import { NoeudMeshUtilisateur } from '../../shared/models/noeud-mesh-utilisateur.model';
import { ContactMeshCore } from '../../shared/models/contact-meshcore.model';

/** Cible de message privé : NoeudMeshUtilisateur ou ContactMeshCore, identifiée par pubkey
 * (MessageMeshLogViewSet est indexé par pubkey_hex). */
interface CibleDm {
  pubkeyHex: string;
  titre: string;
  sousTitre?: string;
}

type Conversation =
  | { type: 'canal'; canal: CanalMeshCore }
  | { type: 'dm'; cible: CibleDm };

/** Chat MeshCore : canaux d'équipe, canaux publics et messages privés dans une même interface.
 * Les canaux d'équipe se créent depuis la fiche équipe ; un DM vise une personne, jamais une
 * équipe (pas d'ambiguïté de routage). */
@Component({
  selector: 'app-meshcore-canaux',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-canaux.component.html',
  styleUrl: './meshcore-canaux.component.scss',
})
export class MeshcoreCanauxComponent implements OnInit, OnDestroy, AfterViewChecked {

  @ViewChild('messagesContainer') messagesContainer?: ElementRef<HTMLDivElement>;
  /** Défilement différé à l'après-rendu : le conteneur n'existe pas pendant le spinner. */
  private doitDefilerEnBas = false;

  canaux: CanalMeshCore[] = [];
  noeuds: NoeudMeshUtilisateur[] = [];
  /** Contacts COMPANION du companion (un répéteur ne se contacte pas en DM). */
  contacts: ContactMeshCore[] = [];
  compagnonPrincipalId: string | null = null;
  /** Canaux captés sans clé locale (CanalMeshCoreDetecte) : lecture seule. */
  canauxDetectes: CanalMeshCoreDetecte[] = [];

  conversationSelectionnee: Conversation | null = null;
  messagesCanal: MessageCanalMeshCore[] = [];
  messagesDm: MessageMeshLog[] = [];

  loadingSidebar = true;
  loadingMessages = false;
  errorMessage = '';

  nouveauMessage = '';
  envoiEnCours = false;

  /** Canal public (ex: "#meteo") : clé dérivée du nom côté serveur (CanalMeshCoreSerializer.validate). */
  nouveauCanalPublicNom = '';
  ajoutCanalEnCours = false;

  private intervalRafraichissement: ReturnType<typeof setInterval> | null = null;

  constructor(
    private canalService: CanalMeshCoreService,
    private dmService: MessageMeshService,
    private noeudService: NoeudMeshUtilisateurService,
    private compagnonService: CompagnonMeshCoreService,
    private contactService: ContactMeshCoreService,
  ) {}

  ngOnInit(): void {
    this.chargerSidebar();
    this.intervalRafraichissement = setInterval(() => {
      if (this.conversationSelectionnee) this.chargerMessages(this.conversationSelectionnee, false);
      this.chargerCanauxDetectes();
      this.rafraichirCanaux();
      this.rafraichirContacts();
    }, 8000);
  }

  /** Recharge la liste des canaux sans spinner (canaux rejoints ailleurs ou créés par le pont). */
  private rafraichirCanaux(): void {
    this.canalService.getAll().subscribe({
      next: (canaux) => { this.canaux = canaux; },
      error: () => { /* non bloquant -- on retentera au prochain cycle */ },
    });
  }

  /** Idem pour les contacts synchronisés par le pont (boucle_contacts). */
  private rafraichirContacts(): void {
    this.contactService.getAll().subscribe({
      next: (contacts) => { this.contacts = contacts.filter(c => c.type_contact === 'COMPANION'); },
      error: () => { /* non bloquant -- on retentera au prochain cycle */ },
    });
  }

  ngOnDestroy(): void {
    if (this.intervalRafraichissement) clearInterval(this.intervalRafraichissement);
  }

  ngAfterViewChecked(): void {
    if (this.doitDefilerEnBas && this.messagesContainer) {
      this.doitDefilerEnBas = false;
      this.defilerEnBas();
    }
  }

  private defilerEnBas(): void {
    const el = this.messagesContainer?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  /** Ne force pas le défilement si l'utilisateur relit l'historique (rafraîchissement toutes les 8 s). */
  private estProcheDuBas(): boolean {
    const el = this.messagesContainer?.nativeElement;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  chargerSidebar(): void {
    this.loadingSidebar = true;
    forkJoin({
      canaux: this.canalService.getAll(),
      noeuds: this.noeudService.getAll(),
      compagnons: this.compagnonService.getAll(),
      contacts: this.contactService.getAll(),
    }).subscribe({
      next: ({ canaux, noeuds, compagnons, contacts }) => {
        this.canaux = canaux;
        this.noeuds = noeuds.filter(n => n.actif);
        this.contacts = contacts.filter(c => c.type_contact === 'COMPANION');
        const principal = compagnons.find(c => c.principal) ?? compagnons[0];
        this.compagnonPrincipalId = principal?.id ?? null;
        this.loadingSidebar = false;
        this.chargerCanauxDetectes();
        if (!this.conversationSelectionnee && canaux.length > 0) {
          this.selectionnerCanal(canaux[0]);
        }
      },
      error: () => { this.errorMessage = 'Impossible de charger les conversations.'; this.loadingSidebar = false; },
    });
  }

  private chargerCanauxDetectes(): void {
    if (!this.compagnonPrincipalId) return;
    this.compagnonService.canauxDetectes(this.compagnonPrincipalId).subscribe({
      next: (data) => { this.canauxDetectes = data; },
      error: () => { /* non bloquant -- simple complément d'information */ },
    });
  }

  selectionnerCanal(canal: CanalMeshCore): void {
    this.conversationSelectionnee = { type: 'canal', canal };
    this.chargerMessages(this.conversationSelectionnee, true);
  }

  /** Liste des cibles DM dédupliquée par pubkey_hex ; le nom du compte prime sur le nom annoncé. */
  get contactsPourDm(): CibleDm[] {
    const parPubkey = new Map<string, CibleDm>();
    for (const n of this.noeuds) {
      parPubkey.set(n.pubkey_hex, {
        pubkeyHex: n.pubkey_hex,
        titre: n.nom_noeud || n.utilisateur_nom || 'Sans nom',
        sousTitre: (n.nom_noeud && n.utilisateur_nom) ? n.utilisateur_nom : undefined,
      });
    }
    for (const c of this.contacts) {
      if (!parPubkey.has(c.pubkey_hex)) {
        parPubkey.set(c.pubkey_hex, { pubkeyHex: c.pubkey_hex, titre: c.nom || c.pubkey_hex.slice(0, 10) });
      }
    }
    return Array.from(parPubkey.values()).sort((a, b) => a.titre.localeCompare(b.titre));
  }

  selectionnerDm(cible: CibleDm): void {
    this.conversationSelectionnee = { type: 'dm', cible };
    this.chargerMessages(this.conversationSelectionnee, true);
  }

  estConversationActive(conv: Conversation): boolean {
    if (!this.conversationSelectionnee) return false;
    if (conv.type === 'canal' && this.conversationSelectionnee.type === 'canal') {
      return conv.canal.id === this.conversationSelectionnee.canal.id;
    }
    if (conv.type === 'dm' && this.conversationSelectionnee.type === 'dm') {
      return conv.cible.pubkeyHex === this.conversationSelectionnee.cible.pubkeyHex;
    }
    return false;
  }

  chargerMessages(conv: Conversation, avecSpinner: boolean): void {
    if (avecSpinner) this.loadingMessages = true;
    // Changement de conversation : on force le défilement en bas. Rafraîchissement auto :
    // seulement si l'utilisateur n'a pas remonté lire l'historique.
    const procheDuBas = avecSpinner || this.estProcheDuBas();
    if (conv.type === 'canal') {
      this.canalService.getMessages(conv.canal.id).subscribe({
        next: (data) => {
          this.messagesCanal = data;
          if (avecSpinner) this.loadingMessages = false;
          if (procheDuBas) this.doitDefilerEnBas = true;
        },
        error: () => { if (avecSpinner) this.loadingMessages = false; },
      });
    } else {
      this.dmService.getPourContact(conv.cible.pubkeyHex).subscribe({
        next: (data) => {
          this.messagesDm = data;
          if (avecSpinner) this.loadingMessages = false;
          if (procheDuBas) this.doitDefilerEnBas = true;
        },
        error: () => { if (avecSpinner) this.loadingMessages = false; },
      });
    }
  }

  /** Canaux d'équipe (`equipe` renseigné) et canaux publics, affichés séparément ; les deux ont un
   * fil de discussion, contrairement aux canaux détectés. */
  get canauxEquipe(): CanalMeshCore[] {
    return this.canaux.filter(c => !!c.equipe);
  }

  get canauxPublics(): CanalMeshCore[] {
    return this.canaux.filter(c => !c.equipe);
  }

  get messagesAffiches(): (MessageCanalMeshCore | MessageMeshLog)[] {
    if (!this.conversationSelectionnee) return [];
    return this.conversationSelectionnee.type === 'canal' ? this.messagesCanal : this.messagesDm;
  }

  envoyer(): void {
    const conv = this.conversationSelectionnee;
    if (!conv || !this.nouveauMessage.trim()) return;
    const contenu = this.nouveauMessage.trim();
    this.envoiEnCours = true;

    if (conv.type === 'canal') {
      this.canalService.envoyerMessage(conv.canal.id, contenu).subscribe({
        next: (message) => {
          this.messagesCanal = [...this.messagesCanal, message];
          this.nouveauMessage = '';
          this.envoiEnCours = false;
          this.doitDefilerEnBas = true;
        },
        error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
      });
    } else {
      if (!this.compagnonPrincipalId) {
        this.errorMessage = 'Aucun companion actif pour envoyer ce message.';
        this.envoiEnCours = false;
        return;
      }
      this.dmService.envoyer(this.compagnonPrincipalId, conv.cible.pubkeyHex, contenu).subscribe({
        next: (message) => {
          this.messagesDm = [...this.messagesDm, message];
          this.nouveauMessage = '';
          this.envoiEnCours = false;
          this.doitDefilerEnBas = true;
        },
        error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
      });
    }
  }

  ajouterCanalPublic(): void {
    let nom = this.nouveauCanalPublicNom.trim();
    if (!nom) return;
    if (!nom.startsWith('#')) nom = `#${nom}`;
    this.ajoutCanalEnCours = true;
    this.canalService.create({ nom }).subscribe({
      next: (canal) => {
        this.canaux = [...this.canaux, canal];
        this.nouveauCanalPublicNom = '';
        this.ajoutCanalEnCours = false;
        this.selectionnerCanal(canal);
        // Le backend a pu fusionner une ligne fantôme de trafic capté : rafraîchir tout de suite.
        this.chargerCanauxDetectes();
      },
      error: () => { this.errorMessage = "Impossible de rejoindre ce canal public."; this.ajoutCanalEnCours = false; },
    });
  }

  // ── Affichage ─────────────────────────────────────────────────────────

  titreConversation(conv: Conversation): string {
    return conv.type === 'canal' ? conv.canal.nom : conv.cible.titre;
  }

  sousTitreConversation(conv: Conversation): string {
    if (conv.type === 'canal') {
      return conv.canal.equipe_nom ? `Canal d'équipe · ${conv.canal.equipe_nom}` : 'Canal public';
    }
    return 'Message privé';
  }

  auteurMessage(m: MessageCanalMeshCore | MessageMeshLog, conv: Conversation): string {
    if (m.direction === 'SORTANT') return m.expediteur_nom || 'Moi';
    if (conv.type === 'dm') return this.titreConversation(conv);
    return 'Mesh';
  }

  statutIcone(statut: StatutMessageMesh): string {
    return { EN_ATTENTE: 'schedule', ENVOYE: 'done', RECU: 'done_all', ECHEC: 'error_outline' }[statut];
  }

  statutClasse(statut: StatutMessageMesh): string {
    return { EN_ATTENTE: 'statut-attente', ENVOYE: 'statut-envoye', RECU: 'statut-recu', ECHEC: 'statut-echec' }[statut];
  }

  statutLibelle(statut: StatutMessageMesh): string {
    return { EN_ATTENTE: 'En attente d\'envoi', ENVOYE: 'Envoyé (accusé de réception reçu)', RECU: 'Reçu', ECHEC: 'Échec de l\'envoi' }[statut];
  }
}
