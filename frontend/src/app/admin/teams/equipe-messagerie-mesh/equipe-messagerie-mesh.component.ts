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

/** DM privés régulateur <-> équipe, uniquement si au moins un membre de l'équipe a un
 * companion MeshCore personnel associé (voir /admin/meshcore-companions, section « Nœuds »).
 * La visibilité réelle de ces messages est imposée côté serveur (leader/régulateur de CETTE
 * équipe uniquement, voir MessageMeshLogViewSet) — ce composant se contente d'afficher ce que
 * l'API accepte de renvoyer, il n'invente pas de restriction supplémentaire côté client. */
@Component({
  selector: 'app-equipe-messagerie-mesh',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './equipe-messagerie-mesh.component.html',
  styleUrl: './equipe-messagerie-mesh.component.scss',
})
export class EquipeMessagerieMeshComponent implements OnChanges, OnDestroy {

  @Input() equipeId!: string;
  /** Canal d'équipe (voir TeamViewSet.provisionner_canal_meshcore) — ses messages sont
   * fusionnés avec les DM dans le même fil, si fourni. */
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

  /** Raison de la suggestion automatique du companion "Via" (voir core/routage_mesh.py côté
   * backend) — affichée pour que l'utilisateur comprenne le choix fait à sa place, et puisse
   * le changer explicitement (le sélecteur "Via" reste toujours modifiable). */
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
      // pollWhileVisible (au lieu d'un setInterval nu) : suspend le rafraîchissement quand
      // l'onglet est en arrière-plan, et rattrape immédiatement au retour au premier plan
      // plutôt que d'attendre jusqu'à 8s de plus — le premier tick (immédiat) est ignoré ici,
      // charger() vient déjà de le faire via chargerMessages(true).
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
    // messageables()/envoyables() (résumés minimaux, jamais l'identité réelle en zone DEMO)
    // plutôt que getAll() (bloqué en zone DEMO, voir NoeudMeshUtilisateurViewSet/
    // CompagnonMeshCoreViewSet) — le filtrage par équipe se fait déjà côté serveur.
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
        // Le canal d'équipe reste affiché même sans membre équipé d'un nœud personnel —
        // seule la composition d'un DM (destinataire) en dépend.
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

  /** Interroge core/routage_mesh.py (via l'endpoint meilleur-pour-contact) pour pré-sélectionner
   * le companion le plus adapté à CE destinataire — contact déjà entendu au plus court en
   * sauts, sinon sa région, sinon le principal. Le sélecteur "Via" reste modifiable ensuite :
   * ce n'est qu'une suggestion, jamais imposée. */
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

  /** Nom lisible de la personne de terrain associée à ce nœud — utilisé pour afficher
   * clairement "à qui" un DM sortant a été adressé et "qui" a répondu, un fil de DM
   * d'équipe mélangeant potentiellement plusieurs membres équipés d'un nœud personnel. */
  private nomPourPubkey(pubkeyHex: string): string {
    const noeud = this.noeudsEquipe.find(n => n.pubkey_hex === pubkeyHex);
    return noeud?.utilisateur_nom || noeud?.nom_noeud || pubkeyHex.slice(0, 8);
  }

  /** Ligne d'attribution d'un DM : "Moi → <destinataire>" (sortant) ou "<expéditeur> → Moi"
   * (entrant) — remarque explicite : sans ça, impossible de savoir à qui un message sortant
   * était adressé, ou qui a répondu, dès que l'équipe a plus d'un membre équipé. */
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
