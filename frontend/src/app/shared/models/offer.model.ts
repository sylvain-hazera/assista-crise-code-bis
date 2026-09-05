import { GeoPoint } from "./geopoint.model";
import { Status } from "./status.model";

export interface OfferType {
  id: string;
  type: string;
  description: string;
}

export interface Offer {
  id: string;                           // UUID
  title: string;
  description?: string | null;
  has_photo: boolean;
  location: GeoPoint | null;            // null si l'offreur n'a pas indiqué d'adresse,
                                         // ou si l'adresse est masquée pour ce lecteur (public)
  latitude?: number | null;
  longitude?: number | null;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  phone_offer?: string | null;
  created_at: string;
  expires_at: string | null;
  status: Status;
  offer_type: string;                   // UUID du OfferType (FK)
  offer_type_nom?: string | null;
  crisis: string | null;
  crisis_nom?: string | null;
  author: string | null;
  author_nom?: string | null;
  author_email?: string | null;
  author_phone?: string | null;
  author_type?: string | null;
  organisation_nom?: string | null;  // dépôt groupé : nom de l'entreprise/association déposante
  groupe_id?: string | null;         // partagé par toutes les offres d'une même soumission groupée
  hebergement_duree?: string | null;
  type_loyer?: string | null;
  loyer_montant_min?: number | null;
  loyer_montant_max?: number | null;
  type_logement?: string | null;
  niveau_logement?: string | null;
  acces_etage?: string | null;
  nombre_pieces?: number | null;
  nombre_chambres?: number | null;
  capacite_adultes?: number | null;
  capacite_enfants?: number | null;
  animaux_acceptes?: boolean;
  jardin?: boolean;
  pmr_compatible?: boolean;
  numero_adeli_rpps?: string | null;
  transport_type?: string | null;
  transport_animaux_precision?: string | null;
  materiel_type?: string | null;
  cuve_contenu?: string | null;
  soutien_type?: string | null;
  diplome_secourisme?: boolean;
  materiel_livraison?: 'A_RECUPERER' | 'LIVRAISON_POSSIBLE' | null;
  confirmation_reglementaire?: boolean;
  immatriculation?: string | null;
  nombre_places_assises?: number | null;  // Transport de personnes : places disponibles en plus du conducteur
  mission?: string | null;
  mission_titre?: string | null;
  materiel_catalogue?: string | null;
  materiel_catalogue_nom?: string | null;
  quantite?: number | null;
  unite?: string | null;
  renouvelable?: boolean;
  presence_physique?: boolean | null; // l'offreur est-il physiquement présent avec ce qu'il propose ? null = offre antérieure à ce champ, inconnu
  competences?: string[];
  competences_libelles?: string[];
  commune?: string | null;
  distance_from_crisis_km?: number | null;
  engagement_statut?: 'EN_ATTENTE' | 'CONFIRME' | 'DECLINE' | 'EN_TRANSIT' | 'ARRIVE' | null;
  engagement_statut_libelle?: string | null;
  actif?: boolean;                    // false = désactivée (politique de désactivation)
}

export interface OfferPayload {
  title: string;
  first_name_offer: string;
  last_name_offer: string;
  email_offer: string;
  latitude: number;
  longitude: number;
  offer_type: string;
  status?: Status;
  expires_at?: string | null;
  crisis?: string | null;
  photo?: File;
}