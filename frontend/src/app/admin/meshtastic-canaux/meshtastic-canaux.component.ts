import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { CanalMeshtasticService } from '../../services/canal-meshtastic.service';
import { MessageMeshtasticService } from '../../services/message-meshtastic.service';
import { NoeudUtilisateurMeshtasticService } from '../../services/noeud-utilisateur-meshtastic.service';
import { CompagnonMeshtasticService } from '../../services/compagnon-meshtastic.service';
import { CanalMeshtastic, MessageCanalMeshtastic, MessageMeshtasticLog } from '../../shared/models/canal-meshtastic.model';
import { NoeudUtilisateurMeshtastic } from '../../shared/models/noeud-utilisateur-meshtastic.model';
import { StatutMessageMesh } from '../../shared/models/canal-meshcore.model';

type Conversation =
  | { type: 'canal'; canal: CanalMeshtastic }
  | { type: 'dm'; noeud: NoeudUtilisateurMeshtastic };

/** Chat Meshtastic unifié — même principe que MeshcoreCanauxComponent (MeshCore). Un DM est
 * chiffré avec la PSK d'un canal partagé, à choisir explicitement (ou laissé au canal principal
 * par défaut) — le PKI (clé publique/privée) est implémenté côté pont mais désactivé à l'envoi
 * (non confirmé en conditions réelles, voir meshtastic-bridge/README.md). */
@Component({
  selector: 'app-meshtastic-canaux',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshtastic-canaux.component.html',
  styleUrl: './meshtastic-canaux.component.scss',
})
export class MeshtasticCanauxComponent implements OnInit, OnDestroy {

  canaux: CanalMeshtastic[] = [];
  noeuds: NoeudUtilisateurMeshtastic[] = [];
  compagnonPrincipalId: string | null = null;

  conversationSelectionnee: Conversation | null = null;
  messagesCanal: MessageCanalMeshtastic[] = [];
  messagesDm: MessageMeshtasticLog[] = [];

  /** Canal dont la PSK sera utilisée pour chiffrer le prochain DM envoyé. */
  canalPourEnvoiId = '';

  loadingSidebar = true;
  loadingMessages = false;
  errorMessage = '';

  nouveauMessage = '';
  envoiEnCours = false;

  private intervalRafraichissement: ReturnType<typeof setInterval> | null = null;

  constructor(
    private canalService: CanalMeshtasticService,
    private dmService: MessageMeshtasticService,
    private noeudService: NoeudUtilisateurMeshtasticService,
    private compagnonService: CompagnonMeshtasticService,
  ) {}

  ngOnInit(): void {
    this.chargerSidebar();
    this.intervalRafraichissement = setInterval(() => {
      if (this.conversationSelectionnee) this.chargerMessages(this.conversationSelectionnee, false);
    }, 8000);
  }

  ngOnDestroy(): void {
    if (this.intervalRafraichissement) clearInterval(this.intervalRafraichissement);
  }

  chargerSidebar(): void {
    this.loadingSidebar = true;
    forkJoin({
      canaux: this.canalService.getAll(),
      noeuds: this.noeudService.getAll(),
      compagnons: this.compagnonService.getAll(),
    }).subscribe({
      next: ({ canaux, noeuds, compagnons }) => {
        this.canaux = canaux;
        this.noeuds = noeuds.filter(n => n.actif);
        const principal = compagnons.find(c => c.principal) ?? compagnons[0];
        this.compagnonPrincipalId = principal?.id ?? null;
        if (!this.canalPourEnvoiId && canaux.length > 0) {
          this.canalPourEnvoiId = (canaux.find(c => c.principal) ?? canaux[0]).id;
        }
        this.loadingSidebar = false;
        if (!this.conversationSelectionnee && canaux.length > 0) {
          this.selectionnerCanal(canaux[0]);
        }
      },
      error: () => { this.errorMessage = 'Impossible de charger les conversations.'; this.loadingSidebar = false; },
    });
  }

  selectionnerCanal(canal: CanalMeshtastic): void {
    this.conversationSelectionnee = { type: 'canal', canal };
    this.chargerMessages(this.conversationSelectionnee, true);
  }

  selectionnerDm(noeud: NoeudUtilisateurMeshtastic): void {
    this.conversationSelectionnee = { type: 'dm', noeud };
    this.chargerMessages(this.conversationSelectionnee, true);
  }

  estConversationActive(conv: Conversation): boolean {
    if (!this.conversationSelectionnee) return false;
    if (conv.type === 'canal' && this.conversationSelectionnee.type === 'canal') {
      return conv.canal.id === this.conversationSelectionnee.canal.id;
    }
    if (conv.type === 'dm' && this.conversationSelectionnee.type === 'dm') {
      return conv.noeud.id === this.conversationSelectionnee.noeud.id;
    }
    return false;
  }

  chargerMessages(conv: Conversation, avecSpinner: boolean): void {
    if (avecSpinner) this.loadingMessages = true;
    if (conv.type === 'canal') {
      this.canalService.getMessages(conv.canal.id).subscribe({
        next: (data) => { this.messagesCanal = data; if (avecSpinner) this.loadingMessages = false; },
        error: () => { if (avecSpinner) this.loadingMessages = false; },
      });
    } else {
      this.dmService.getPourContact(conv.noeud.node_num).subscribe({
        next: (data) => { this.messagesDm = data; if (avecSpinner) this.loadingMessages = false; },
        error: () => { if (avecSpinner) this.loadingMessages = false; },
      });
    }
  }

  get messagesAffiches(): (MessageCanalMeshtastic | MessageMeshtasticLog)[] {
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
        },
        error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
      });
    } else {
      // PKI désactivé à l'envoi côté pont (voir meshtastic-bridge/README.md — non confirmé en
      // conditions réelles, contrairement au DM chiffré par PSK de canal) : toujours passer un
      // canal, résolu sur le principal si aucun n'est explicitement choisi.
      if (!this.compagnonPrincipalId) {
        this.errorMessage = 'Aucun companion disponible pour envoyer ce message.';
        this.envoiEnCours = false;
        return;
      }
      this.dmService.envoyer(this.compagnonPrincipalId, this.canalPourEnvoiId || null, conv.noeud.node_num, contenu).subscribe({
        next: (message) => {
          this.messagesDm = [...this.messagesDm, message];
          this.nouveauMessage = '';
          this.envoiEnCours = false;
        },
        error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
      });
    }
  }

  // ── Affichage ─────────────────────────────────────────────────────────

  titreConversation(conv: Conversation): string {
    return conv.type === 'canal' ? conv.canal.nom : (conv.noeud.nom_noeud || conv.noeud.utilisateur_nom || 'Sans nom');
  }

  sousTitreConversation(conv: Conversation): string {
    if (conv.type === 'canal') {
      return conv.canal.equipe_nom ? `Canal d'équipe · ${conv.canal.equipe_nom}` : 'Canal général';
    }
    return 'Message privé (chiffré via le canal choisi ci-dessous)';
  }

  auteurMessage(m: MessageCanalMeshtastic | MessageMeshtasticLog, conv: Conversation): string {
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
    return { EN_ATTENTE: 'En attente d\'envoi', ENVOYE: 'Publié sur le broker (pas de confirmation de réception)', RECU: 'Reçu', ECHEC: 'Échec de l\'envoi' }[statut];
  }
}
