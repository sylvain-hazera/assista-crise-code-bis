export interface AddressResult {
  label: string;      // adresse complète formatée (ex: "12 Rue de la Mairie 38000 Grenoble")
  street: string;      // numéro + voie (ex: "12 Rue de la Mairie")
  postcode: string;
  city: string;
  citycode: string;    // code INSEE de la commune
  latitude: number;
  longitude: number;
}
