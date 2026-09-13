import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { CanalMeshCoreService } from '../../services/canal-meshcore.service';
import { MessageMeshService } from '../../services/message-mesh.service';
import { NoeudMeshUtilisateurService } from '../../services/noeud-mesh-utilisateur.service';
import { CompagnonMeshCoreService } from '../../services/compagnon-meshcore.service';
import { CanalMeshCore, MessageCanalMeshCore, MessageMeshLog, StatutMessageMesh } from '../../shared/models/canal-meshcore.model';
import { NoeudMeshUtilisateur } from '../../shared/models/noeud-mesh-utilisateur.model';

type Conversation =
  | { type: 'canal'; canal: CanalMeshCore }
  | { type: 'dm'; noeud: NoeudMeshUtilisateur };

/** Chat MeshCore unifié : canaux d'équipe (coordination générale, un canal = une équipe, voir
 * TeamViewSet.provisionner_canal_meshcore) ET messages privés (DM, un fil par personne) dans
 * la même interface — sidebar de conversations + fil de discussion, comme un client de
 * messagerie classique (inspiré de github.com/Daring-Designs/meshtastic-ui-ha : sidebar de
 * conversations mêlant canaux et DM, indicateurs de statut d'envoi par message).
 *
 * Un canal d'équipe se crée depuis la fiche équipe (TeamsComponent, bouton "Créer le canal
 * MeshCore") — cette page ne fait que lister/discuter sur ceux qui existent déjà. Les DM,
 * eux, ciblent une personne précise parmi celles ayant un nœud MeshCore associé
 * (NoeudMeshUtilisateur) — jamais une équipe entière, pour éviter l'ambiguïté de routage
 * qu'avait l'ancien système (un message attribué à `expediteur.teams.first()`, arbitraire dès
 * qu'on appartient à plusieurs équipes). */
@Component({
  selector: 'app-meshcore-canaux',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './meshcore-canaux.component.html',
  styleUrl: './meshcore-canaux.component.scss',
})
export class MeshcoreCanauxComponent implements OnInit, OnDestroy {

  canaux: CanalMeshCore[] = [];
  noeuds: NoeudMeshUtilisateur[] = [];
  compagnonPrincipalId: string | null = null;

  conversationSelectionnee: Conversation | null = null;
  messagesCanal: MessageCanalMeshCore[] = [];
  messagesDm: MessageMeshLog[] = [];

  loadingSidebar = true;
  loadingMessages = false;
  errorMessage = '';

  nouveauMessage = '';
  envoiEnCours = false;

  private intervalRafraichissement: ReturnType<typeof setInterval> | null = null;

  constructor(
    private canalService: CanalMeshCoreService,
    private dmService: MessageMeshService,
    private noeudService: NoeudMeshUtilisateurService,
    private compagnonService: CompagnonMeshCoreService,
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
        this.loadingSidebar = false;
        if (!this.conversationSelectionnee && canaux.length > 0) {
          this.selectionnerCanal(canaux[0]);
        }
      },
      error: () => { this.errorMessage = 'Impossible de charger les conversations.'; this.loadingSidebar = false; },
    });
  }

  selectionnerCanal(canal: CanalMeshCore): void {
    this.conversationSelectionnee = { type: 'canal', canal };
    this.chargerMessages(this.conversationSelectionnee, true);
  }

  selectionnerDm(noeud: NoeudMeshUtilisateur): void {
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
      this.dmService.getPourContact(conv.noeud.pubkey_hex).subscribe({
        next: (data) => { this.messagesDm = data; if (avecSpinner) this.loadingMessages = false; },
        error: () => { if (avecSpinner) this.loadingMessages = false; },
      });
    }
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
        },
        error: () => { this.errorMessage = "Échec de l'envoi."; this.envoiEnCours = false; },
      });
    } else {
      if (!this.compagnonPrincipalId) {
        this.errorMessage = 'Aucun companion actif pour envoyer ce message.';
        this.envoiEnCours = false;
        return;
      }
      this.dmService.envoyer(this.compagnonPrincipalId, conv.noeud.pubkey_hex, contenu).subscribe({
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
