import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { of, Subscription } from 'rxjs';

import { NoeudMeshUtilisateurService } from '../../../services/noeud-mesh-utilisateur.service';
import { CompagnonMeshCoreService } from '../../../services/compagnon-meshcore.service';
import { MessageMeshService } from '../../../services/message-mesh.service';
import { CanalMeshCoreService } from '../../../services/canal-meshcore.service';
import { NoeudMeshUtilisateur } from '../../../shared/models/noeud-mesh-utilisateur.model';
import { CompagnonMeshCore } from '../../../shared/models/compagnon-meshcore.model';
import { MessageMeshLog, MessageCanalMeshCore } from '../../../shared/models/canal-meshcore.model';
import { pollWhileVisible } from '../../../shared/utils/polling.util';

const INTERVALLE_POLLING_MESSAGES_MS = 8_000;

/** DM régulateur <-> équipe, si un membre a un companion MeshCore personnel. La visibilité est
 * imposée côté serveur (MessageMeshLogViewSet). */
@Component({
  selector: 'app-equipe-messagerie-mesh',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './equipe-messagerie-mesh.component.html',
  styleUrl: './equipe-messagerie-mesh.component.scss',
})
export class EquipeMessagerieMeshComponent implements OnChanges, OnDestroy {

  @Input() equipeId!: string;
  /** Canal d'équipe, fusionné avec les DM dans le même fil. */
  @Input() canalId?: string | null;

  chargement = true;
  equipee = false;
  noeudsEquipe: NoeudMeshUtilisateur[] = [];
  compagnons: CompagnonMeshCore[] = [];
  messagesDm: MessageMeshLog[] = [];
  messagesCanal: MessageCanalMeshCore[] = [];
  erreur = '';

  destinataireId = '';
  compagnonId = '';
  nouveauMessage = '';
  envoiEnCours = false;

  /** Raison de la suggestion du companion « Via » (core/routage_mesh.py), modifiable. */
  suggestionCompagnonRaison = '';

  private pollingSub?: Subscription;

  constructor(
    private noeudService: NoeudMeshUtilisateurService,
    private compagnonService: CompagnonMeshCoreService,
    private messageService: MessageMeshService,
    private canalService: CanalMeshCoreService,
  ) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['equipeId'] && this.equipeId) {
      this.charger();
      this.pollingSub?.unsubscribe();
      // pollWhileVisible : suspendu en arrière-plan ; le premier tick est ignoré (charger() vient
      // de charger).
      let premierTick = true;
      this.pollingSub = pollWhileVisible(() => of(null), INTERVALLE_POLLING_MESSAGES_MS).subscribe(() => {
        if (premierTick) { premierTick = false; return; }
        this.chargerMessages(false);
      });
    }
  }

  ngOnDestroy(): void {
    this.pollingSub?.unsubscribe();
  }

  private charger(): void {
    this.chargement = true;
    // messageables()/envoyables() : résumés sans identité en zone DEMO (getAll() y est bloqué).
    this.noeudService.messageables(this.equipeId).subscribe({
      next: (noeuds) => {
        this.noeudsEquipe = noeuds as NoeudMeshUtilisateur[];
        this.equipee = this.noeudsEquipe.length > 0;
        if (this.equipee) {
          this.destinataireId = this.noeudsEquipe[0].id;
          this.compagnonService.envoyables().subscribe(compagnons => {
            this.compagnons = compagnons as CompagnonMeshCore[];
            this.compagnonId = this.compagnons.find(c => c.principal)?.id || this.compagnons[0]?.id || '';
            this.suggererCompagnon();
          });
        }
        // Le canal d'équipe s'affiche même sans membre équipé ; seuls les DM en dépendent.
        this.chargerMessages(true);
      },
      error: () => { this.erreur = "Impossible de vérifier l'équipement MeshCore de cette équipe."; this.chargement = false; },
    });
  }

  chargerMessages(avecSpinner: boolean): void {
    if (avecSpinner) this.chargement = true;
    this.messageService.getPourEquipe(this.equipeId).subscribe({
      next: (data) => { this.messagesDm = data; if (!this.canalId) this.chargement = false; },
      error: () => { if (avecSpinner && !this.canalId) this.chargement = false; },
    });
    if (this.canalId) {
      this.canalService.getMessages(this.canalId).subscribe({
        next: (data) => { this.messagesCanal = data; this.chargement = false; },
        error: () => { this.chargement = false; },
      });
    }
  }

  get destinatairePubkey(): string | null {
    return this.noeudsEquipe.find(n => n.id === this.destinataireId)?.pubkey_hex || null;
  }

  onDestinataireChange(): void {
    this.suggererCompagnon();
  }

  /** Pré-sélectionne le companion le plus adapté (meilleur-pour-contact) : plus court en sauts,
   * sinon même région, sinon le principal. */
  private suggererCompagnon(): void {
    this.suggestionCompagnonRaison = '';
    if (!this.destinatairePubkey || this.compagnons.length < 2) return;
    this.compagnonService.meilleurPourContact(this.destinatairePubkey).subscribe({
      next: (suggestion) => {
        if (suggestion.compagnon_id && this.compagnons.some(c => c.id === suggestion.compagnon_id)) {
          this.compagnonId = suggestion.compagnon_id;
          this.suggestionCompagnonRaison = suggestion.raison;
        }
      },
      error: () => {},
    });
  }

  /** Nom de la personne associée au nœud. */
  private nomPourPubkey(pubkeyHex: string): string {
    const noeud = this.noeudsEquipe.find(n => n.pubkey_hex === pubkeyHex);
    return noeud?.utilisateur_nom || noeud?.nom_noeud || pubkeyHex.slice(0, 8);
  }

  /** Attribution d'un DM : « Moi → destinataire » ou « expéditeur → Moi ». */
  attributionDm(m: MessageMeshLog): string {
    const autre = this.nomPourPubkey(m.contact_pubkey_hex);
    return m.direction === 'SORTANT' ? `Moi → ${autre}` : `${m.expediteur_nom || autre} → Moi`;
  }

  envoyer(): void {
    if (!this.nouveauMessage.trim() || !this.compagnonId || !this.destinatairePubkey) return;
    this.envoiEnCours = true;
    this.messageService.envoyer(this.compagnonId, this.destinatairePubkey, this.nouveauMessage.trim()).subscribe({
      next: (message) => {
        this.messagesDm = [...this.messagesDm, message];
        this.nouveauMessage = '';
        this.envoiEnCours = false;
      },
      error: () => { this.erreur = "Échec de l'envoi du message."; this.envoiEnCours = false; },
    });
  }
}
