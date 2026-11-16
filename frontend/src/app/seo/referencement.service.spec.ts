import { TestBed } from '@angular/core/testing';
import { ReferencementService, cheminDe, enTeteDe } from './referencement.service';
import { fournisseursDeTest } from '../testing/test-providers';

const AC = 'www.assista-crise.fr';
const RR = 'app.reserve-resilience.org';

describe('Référencement', () => {
  describe('cheminDe', () => {
    it("ramène /accueil à la racine et écarte paramètres et ancre", () => {
      expect(cheminDe('/accueil')).toBe('/');
      expect(cheminDe('/')).toBe('/');
      expect(cheminDe('/guide?utm_source=essai')).toBe('/guide');
      expect(cheminDe('/guide/#haut')).toBe('/guide');
    });
  });

  describe('enTeteDe', () => {
    it("donne à l'accueil le nom et le slogan de la marque du domaine", () => {
      expect(enTeteDe('/accueil', AC, 'Assista-Crise').titre)
        .toBe('Assista-Crise — entraide et gestion de crise pour les communes');

      // Le nom reçu de l'API n'est pas encore celui de la marque au tout premier affichage :
      // c'est le domaine qui fait foi, comme pour le serveur web.
      const reserve = enTeteDe('/accueil', RR, 'Assista-Crise');
      expect(reserve.titre).toBe("Réserve Résilience - Casques Jaunes — entraide en situation d'urgence");
      expect(reserve.description).toContain('Réserve Résilience - Casques Jaunes');
      expect(reserve.description).not.toContain('Assista-Crise');
      expect(reserve.canonique).toBe('https://app.reserve-resilience.org/');
    });

    it('donne à une page publique son titre, sa description et son adresse canonique', () => {
      const guide = enTeteDe('/guide?departement=42', RR, 'x');
      expect(guide.titre).toBe('Guide des risques majeurs — Réserve Résilience - Casques Jaunes');
      expect(guide.description).toContain('risques majeurs');
      expect(guide.canonique).toBe('https://app.reserve-resilience.org/guide');
    });

    it("n'offre aucune adresse canonique aux pages privées", () => {
      for (const url of ['/dossier-suivi/abc', '/connexion-magique/u/t', '/admin/missions', '/login', '/mon-equipe/4']) {
        const enTete = enTeteDe(url, AC, 'Assista-Crise');
        expect(enTete.canonique).withContext(url).toBeNull();
        expect(enTete.titre).withContext(url).toBe('Assista-Crise');
      }
    });

    it("ne propose pas aux moteurs un hôte qui n'est pas celui d'une marque", () => {
      const satellite = enTeteDe('/guide', '192.168.1.20', 'Mairie de Saint-Étienne');
      expect(satellite.canonique).toBeNull();
      // … mais l'onglet porte bien le nom que l'API a donné.
      expect(satellite.titre).toBe('Guide des risques majeurs — Mairie de Saint-Étienne');
    });
  });

  describe('ReferencementService', () => {
    let service: ReferencementService;
    const lienCanonique = () => document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    const balise = (selecteur: string) => document.head.querySelector<HTMLMetaElement>(selecteur)?.content;

    beforeEach(() => {
      TestBed.configureTestingModule({ providers: fournisseursDeTest() });
      service = TestBed.inject(ReferencementService);
    });

    afterEach(() => {
      lienCanonique()?.remove();
      document.head.querySelectorAll('meta[name="robots"], meta[name="description"], meta[property^="og:"]')
        .forEach((b) => b.remove());
    });

    it("pose titre, description et adresse canonique d'une page publique", () => {
      service.appliquer({ titre: 'Guide — Essai', description: 'Une description.', canonique: 'https://exemple.fr/guide' });

      expect(document.title).toBe('Guide — Essai');
      expect(balise('meta[name="description"]')).toBe('Une description.');
      expect(balise('meta[property="og:title"]')).toBe('Guide — Essai');
      expect(lienCanonique()?.href).toBe('https://exemple.fr/guide');
      expect(balise('meta[name="robots"]')).toBeUndefined();
    });

    it("retire l'adresse canonique et interdit l'indexation en passant sur une page privée", () => {
      service.appliquer({ titre: 'Guide', description: 'd', canonique: 'https://exemple.fr/guide' });
      service.appliquer({ titre: 'Essai', description: 'd', canonique: null });

      expect(lienCanonique()).toBeNull();
      expect(balise('meta[name="robots"]')).toBe('noindex, nofollow');

      // … et tout revient en retournant sur une page publique, sans doublon.
      service.appliquer({ titre: 'Guide', description: 'd', canonique: 'https://exemple.fr/guide' });
      expect(document.head.querySelectorAll('link[rel="canonical"]').length).toBe(1);
      expect(balise('meta[name="robots"]')).toBeUndefined();
    });
  });
});
