"""Metadata of a document, from its path, its file name and its text: no file of the corpus describes them.

Everything here is a pure function of (relative path, format, text, text layer), so it is unit-tested on
real file names without touching the corpus.
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from py3langid.langid import MODEL_FILE, LanguageIdentifier

# ---------------------------------------------------------------------------------------------------
# Document types: the first rule whose pattern matches the relative path wins, so the order matters
# (an annex of the CODIR is not a CODIR minute; a "Photo tableau" is a photo before it is a strategy).
# The label is French: it goes into the context line of the chunks (step 4).
# ---------------------------------------------------------------------------------------------------
DOC_TYPES = [
    # (type, pattern on the relative path, label)
    ("codir_annex", r"CODIR/Annexes/", "Annexe du CODIR"),
    ("codir_minutes", r"PV_CODIR_|CODIR/20\d\d/|Modele PV CODIR", "PV du CODIR"),
    ("board_minutes", r"PV_signes/|Projets_PV/", "PV du conseil d'administration"),
    ("board_convocation", r"Convocations/|Modele convocation CA", "Convocation du conseil d'administration"),
    ("agm_minutes", r"/AG/", "PV de l'assemblée générale"),
    ("copil_minutes", r"COPIL_", "COPIL du projet Atlas"),
    ("safety_committee", r"Comite PBW|/CPPT/", "Comité de sécurité"),
    ("monthly_report", r"Reporting_mensuel/Reporting ", "Reporting mensuel"),
    ("management_comments", r"Commentaires de gestion", "Commentaires de gestion"),
    ("production_report", r"Rapports_mensuels/|Maandrapporten/", "Rapport de production"),
    ("service_note", r"Notes_de_service/", "Note de service"),
    ("supplier_invoice", r"Factures_fournisseurs/", "Facture fournisseur"),
    ("delivery_note", r"Bons_de_livraison/", "Bon de livraison"),
    ("photo", r"/IMG_\d{8}|/Photo ", "Photo"),
    ("org_chart", r"Organigramme", "Organigramme"),
    ("nonconformity", r"Non_conformites/", "Fiche de non-conformité"),
    ("sales_quote", r"Offres/DV-", "Offre de prix"),
    ("supplier_quote", r"Ligne_L4/Offre ", "Offre fournisseur"),
    ("job_offer", r"Recrutement/Offres/", "Offre d'emploi"),
    ("product_sheet", r"Fiches_produits/", "Fiche produit"),
    ("press_release", r"Communiques_presse/", "Communiqué de presse"),
    ("newsletter", r"Newsletter/", "Newsletter Calorvia Info"),
    ("intranet_page", r"Intranet/", "Page intranet"),
    ("maintenance_report", r"Fiches_intervention/", "Fiche d'intervention"),
    ("contract", r"Contrats/|Supply agreement|Avenant|Onderhoudscontract", "Contrat"),
    ("policy", r"Politique|Charte|Reglement de travail", "Politique"),
    ("procedure", r"Procedure|Procedures/|Consignes", "Procédure"),
    ("capex_request", r"Demande capex", "Demande d'investissement"),
    ("budget", r"Budget", "Budget"),
    ("price_list", r"Tarifs?/|Tarif ", "Tarif"),
    ("sales_meeting", r"Reunions_commerciales/", "Compte rendu de réunion commerciale"),
    ("dashboard", r"Tableaux_de_bord/|Indicateurs/", "Tableau de bord"),
    ("schedule", r"Planning", "Planning"),
    ("site_plan", r"Plans/|Plattegrond|Plans d_acces", "Plan"),
    ("letter", r"Courriers?/|Courrier |Lettre |Terugroepbrief|Brief ", "Courrier"),
    ("incident_report", r"Incidentrapport|Rapport incident", "Rapport d'incident"),
    ("strategy", r"Strategie/", "Document stratégique"),
    ("erp_tender", r"Appel_offres_ERP/", "Appel d'offres ERP"),
    ("project_document", r"Projet_Atlas_ERP/Documentation/", "Documentation du projet Atlas"),
    ("account_plan", r"Plan de compte|Accountplan", "Plan de compte client"),
    ("action_plan", r"Actieplan|Plan d'action", "Plan d'action"),
    ("diagram", r"Architecture/|Schema ", "Schéma"),
    ("chart", r"10_RSE/.*\.png$", "Graphique"),
    ("faq", r"/FAQ ", "FAQ"),
    ("certificate", r"Attestation", "Attestation"),
    ("poster", r"Affiche", "Affiche"),
    ("minutes", r"/PV ", "Procès-verbal"),
    ("report", r"Rapport|Verslag|Bilan|Synthese", "Rapport"),
    ("workbook", r"\.(xlsx|csv)$", "Classeur"),  # any other workbook: registers, follow-ups, exports
]


def doc_type(relative_path):
    """(type, French label) of a document; ('other', 'Document') when no rule matches."""
    for kind, pattern, label in DOC_TYPES:
        if re.search(pattern, relative_path):
            return kind, label
    return "other", "Document"


def department(relative_path):
    """The first folder without its number: '03_Production/Gent/...' -> 'Production'."""
    return re.sub(r"^\d+_", "", PurePosixPath(relative_path).parts[0])


def source_type(fmt, has_text_layer):
    """How the content is read: text, table (workbooks, CSV), image, or scan (a PDF without text layer)."""
    if fmt in {"jpg", "jpeg", "png"}:
        return "image"
    if fmt == "pdf" and has_text_layer is False:
        return "scan"
    if fmt in {"xlsx", "csv"}:
        return "table"
    return "text"


# ---------------------------------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------------------------------
@dataclass
class DocDate:
    start: date
    end: date        # last day the document covers: = start for a day, end of month for a month...
    precision: str   # day, month, quarter, year, range
    source: str      # filename, content, or photo (the day the picture was taken, not the subject's date)


MONTHS = {
    # French (with and without accents), Dutch, English
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6, "juli": 7, "augustus": 8,
    "oktober": 10, "december": 12,
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "august": 8, "october": 10,
}
MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))  # longest first: "juillet" before "juil"

# Only the beginning of the text: the date of a document is in its heading, later dates are about other things
CONTENT_WINDOW = 600


def make_date(year, month, day):
    """A date, or None if the numbers don't form one (month 20, 31 April...)."""
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def end_of_month(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def day(year, month, d, source="filename"):
    value = make_date(year, month, d)
    return DocDate(value, value, "day", source) if value else None


def filename_date(name):
    """The date a file name states precisely (day, month, quarter, year range), or None.

    A bare year ('Tarif 2026', 'NC-2025-047') is not handled here: see filename_year().
    """
    if m := re.search(r"IMG_(20\d\d)(\d\d)(\d\d)", name):
        return day(*m.groups(), source="photo")
    if m := re.search(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)", name):            # 2025-10-13
        return day(*m.groups())
    if m := re.search(r"(?<!\d)(20\d\d)(\d\d)(\d\d)(?!\d)", name):              # COPIL_..._20260205
        return day(*m.groups())
    if m := re.search(r"(?<!\d)(\d\d)-(\d\d)-(20\d\d)(?!\d)", name):            # 16-12-2025
        d, month, year = m.groups()
        return day(year, month, d)
    if m := re.search(r"\bT([1-4]) (20\d\d)\b", name):                         # T1 2026
        quarter, year = int(m[1]), int(m[2])
        return DocDate(date(year, 3 * quarter - 2, 1), end_of_month(year, 3 * quarter), "quarter", "filename")
    if m := re.search(r"(?<!\d)(20\d\d)-(0[1-9]|1[0-2])(?![\d-])", name):       # 2026-03, not 2025-2026 nor TM-2025-0391
        year, month = int(m[1]), int(m[2])
        return DocDate(date(year, month, 1), end_of_month(year, month), "month", "filename")
    if m := re.search(rf"\b({MONTH_NAMES}) (20\d\d)\b", name, re.IGNORECASE):  # decembre 2025
        year, month = int(m[2]), MONTHS[m[1].lower()]
        return DocDate(date(year, month, 1), end_of_month(year, month), "month", "filename")
    if m := re.search(r"(?<!\d)(20\d\d)-(20\d\d)(?!\d)", name):                 # 2025-2026
        first, last = int(m[1]), int(m[2])
        if first < last:
            return DocDate(date(first, 1, 1), date(last, 12, 31), "range", "filename")
    return None


def content_date(text, first_line_only=False):
    """The first date written at the top of a text: 13/10/2025, 13 octobre 2025, 1er avril 2026, 26 januari 2026.

    first_line_only: for workbooks, whose first line is the title and whose next lines are data (the first
    date of a list of serial numbers is a production date, not the date of the list).
    """
    head = text.split("\n", 1)[0] if first_line_only else text[:CONTENT_WINDOW]
    numeric = re.search(r"(?<!\d)(\d{1,2})/(\d{1,2})/(20\d\d)(?!\d)", head)
    written = re.search(rf"(?<!\d)(\d{{1,2}})(?:er)?\s+({MONTH_NAMES})\s+(20\d\d)(?!\d)", head, re.IGNORECASE)
    candidates = []
    if numeric:
        candidates.append((numeric.start(), day(numeric[3], numeric[2], numeric[1], source="content")))
    if written:
        month = MONTHS[written[2].lower()]
        candidates.append((written.start(), day(written[3], month, written[1], source="content")))
    candidates = [(position, d) for position, d in candidates if d]
    return min(candidates, key=lambda c: c[0])[1] if candidates else None  # the earliest in the text


def filename_year(name):
    """A year alone in a file name, as a last resort: 'Tarif 2026' -> 2026."""
    if m := re.search(r"(?<!\d)(20\d\d)(?!\d)", name):
        year = int(m[1])
        return DocDate(date(year, 1, 1), date(year, 12, 31), "year", "filename")
    return None


def document_date(relative_path, text, is_table=False):
    """The date of a document: precise file name, else the top of its text, else a year in the file name."""
    name = PurePosixPath(relative_path).name
    return filename_date(name) or content_date(text, first_line_only=is_table) or filename_year(name)


# ---------------------------------------------------------------------------------------------------
# Versions and status
# ---------------------------------------------------------------------------------------------------
MARKERS = [
    # (marker, pattern on the relative path). Every marker found is kept, to analyse the traps later.
    ("template", r"Modeles/|\bModele\b"),
    ("duplicate_folder", r"Doublons/"),
    ("copy", r" - copie\b|\bCopie de\b|\(\d\)\.\w+$"),
    ("archive", r"99_Archives/"),
    ("draft", r"(?i)\bprojet (?:PV|v\d)"),  # not 'Le projet Atlas en 10 questions': a project, not a draft
    ("signed", r"\bsign[ée]|PV_signes/"),  # the 2026 minutes don't say it in their name, their folder does
    ("approved", r"\bapprouv[ée]"),
    ("final_in_name", r"\bFINAL\b"),  # a claim of the file name, not a fact: 'Budget 2026 v2 FINAL' is v2
]

# The status is the strongest marker, in this order: a template or a copy is never the reference,
# whatever else its name says.
STATUS_ORDER = ["template", "duplicate_folder", "copy", "archive", "draft", "signed", "approved"]


def version(relative_path):
    """The version written in the file name: 'v2', 'rev C', or None."""
    name = PurePosixPath(relative_path).name
    if m := re.search(r"(?<![A-Za-z])[vV](\d+)\b", name):  # not \b: in '_v2' the underscore is a word character
        return f"v{m[1]}"
    if m := re.search(r"\brev ([A-Z])\b", name):
        return f"rev {m[1]}"
    return None


def markers(relative_path):
    return [marker for marker, pattern in MARKERS if re.search(pattern, relative_path)]


def status(found_markers):
    """'template', 'copy', 'archive', 'draft', 'signed', 'approved', or None when nothing is said."""
    for marker in STATUS_ORDER:
        if marker in found_markers:
            return "copy" if marker == "duplicate_folder" else marker
    return None


# ---------------------------------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------------------------------
_identifier = None


def detect_language(text, min_words=5, min_probability=0.9):
    """'fr', 'nl', 'en' or 'de' for a text; None when there is too little text or the guess is unsure."""
    global _identifier
    if len(text.split()) < min_words:
        return None
    if _identifier is None:  # loading the model takes a moment: only once, and only when needed
        _identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
        _identifier.set_languages(["fr", "nl", "en", "de"])
    language, probability = _identifier.classify(text)
    return language if probability >= min_probability else None


# ---------------------------------------------------------------------------------------------------
def extract_metadata(relative_path, fmt, text, has_text_layer):
    """Every metadata field of a document, as a dict of the Document fields it fills."""
    kind, label = doc_type(relative_path)
    found = markers(relative_path)
    kind_of_source = source_type(fmt, has_text_layer)
    when = document_date(relative_path, text, is_table=kind_of_source == "table")
    return {
        "department": department(relative_path),
        "doc_type": kind,
        "doc_label": label,
        "doc_date": when.start if when else None,
        "date_end": when.end if when else None,
        "date_precision": when.precision if when else None,
        "date_source": when.source if when else None,
        "version": version(relative_path),
        "status": status(found),
        "markers": found,
        "language": detect_language(text),
        "source_type": kind_of_source,
    }
