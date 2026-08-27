import csv
import io
import zipfile


def _write_csv(zf, filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    zf.writestr(filename, buffer.getvalue())


def build_crisis_export_zip(crise):
    """Construit en mémoire un zip multi-CSV couvrant l'intégralité de la main courante
    d'une crise : journal d'audit, dossiers (historique + commentaires), institutions
    impliquées, points opérationnels (+ inventaire, + disponibilités d'équipe), et
    délégations de compétence. Un CSV par table plutôt qu'un unique fichier plat : chaque
    table a une forme différente, et un CSV par table reste ouvrable tel quel dans un
    tableur sans post-traitement."""

    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:

        _write_csv(
            zf, "audit_log.csv",
            ["date", "utilisateur", "institution", "action", "objet_type", "objet_id", "succes", "commentaire"],
            [
                (
                    log.date_action.isoformat(), log.utilisateur.email if log.utilisateur else "",
                    log.institution.nom if log.institution else "", log.action.libelle,
                    log.objet_type, log.objet_id or "", log.succes, log.commentaire or "",
                )
                for log in crise.audit_logs.select_related("utilisateur", "institution", "action").order_by("date_action")
            ],
        )

        dossiers = list(crise.dossiers.all())
        _write_csv(
            zf, "dossiers.csv",
            ["numero", "statut", "date_creation"],
            [(d.numero, d.statut, d.date_creation.isoformat()) for d in dossiers],
        )

        historique_rows = []
        commentaires_rows = []
        for d in dossiers:
            for h in d.historique.select_related("auteur").order_by("date_creation"):
                historique_rows.append((
                    d.numero, h.date_creation.isoformat(), h.auteur.email if h.auteur else "",
                    h.evenement, h.commentaire or "",
                ))
            for c in d.commentaires.select_related("auteur").order_by("date_creation"):
                commentaires_rows.append((
                    d.numero, c.date_creation.isoformat(), c.auteur.email if c.auteur else "", c.commentaire,
                ))
        _write_csv(zf, "dossiers_historique.csv", ["dossier", "date", "auteur", "evenement", "commentaire"], historique_rows)
        _write_csv(zf, "dossiers_commentaires.csv", ["dossier", "date", "auteur", "commentaire"], commentaires_rows)

        _write_csv(
            zf, "institutions_impliquees.csv",
            ["institution", "type_implication", "responsable", "actif", "date_creation", "commentaire"],
            [
                (
                    i.institution.nom, i.type_implication, i.responsable.email if i.responsable else "",
                    i.actif, i.date_creation.isoformat(), i.commentaire or "",
                )
                for i in crise.implications.select_related("institution", "responsable").order_by("date_creation")
            ],
        )

        points = list(crise.points_operationnels.select_related("type", "responsable__institution"))
        _write_csv(
            zf, "points_operationnels.csv",
            ["nom", "type", "institution", "responsable", "adresse", "date_ouverture", "date_fermeture", "actif"],
            [
                (
                    p.nom, p.type.libelle if p.type else "",
                    p.responsable.institution.nom if p.responsable and p.responsable.institution else "",
                    p.responsable.email if p.responsable else "", p.adresse or "",
                    p.date_ouverture.isoformat() if p.date_ouverture else "",
                    p.date_fermeture.isoformat() if p.date_fermeture else "", p.actif,
                )
                for p in points
            ],
        )

        materiels_rows = []
        dispo_rows = []
        for p in points:
            for m in p.materiels.select_related("item", "responsable"):
                materiels_rows.append((
                    p.nom, m.item.nom, m.get_niveau_stock_display(), m.nom, m.quantite, m.unite,
                    m.get_statut_display(), m.responsable.email if m.responsable else "", m.date_maj.isoformat(),
                ))
            for dispo in p.disponibilites_equipe.select_related("membre"):
                dispo_rows.append((p.nom, dispo.membre.email, dispo.date.isoformat(), dispo.creneau))
        _write_csv(
            zf, "points_inventaire.csv",
            ["point", "item", "niveau_stock", "precision", "quantite", "unite", "statut", "responsable", "date_maj"],
            materiels_rows,
        )
        _write_csv(zf, "points_disponibilites_equipe.csv", ["point", "membre", "date", "creneau"], dispo_rows)

        _write_csv(
            zf, "delegations_competences.csv",
            ["institution_source", "institution_cible", "competence", "departements", "communes", "active", "date_debut", "date_fin", "commentaire"],
            [
                (
                    d.institution_source.nom, d.institution_cible.nom, d.competence.nom,
                    ",".join(d.departements or []), ",".join(d.communes or []),
                    d.active, d.date_debut.isoformat(), d.date_fin.isoformat() if d.date_fin else "",
                    d.commentaire or "",
                )
                for d in crise.delegations_competences.select_related("institution_source", "institution_cible", "competence")
            ],
        )

    buffer.seek(0)
    return buffer
