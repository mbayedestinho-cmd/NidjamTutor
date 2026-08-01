"""
TuteurTD — Mise en relation parents ↔ répétiteurs de maison (N'Djamena)
Version production-ready (P0 appliqués) — Streamlit + Supabase

Secrets Streamlit requis :
  SUPABASE_URL
  SUPABASE_ANON_KEY
  APP_URL (optionnel, pour les liens d'édition)

Supabase requis :
  - tables repetiteurs, avis
  - RPCs : inserer_nouveau_repetiteur, get_repetiteur_by_token,
           update_repetiteur_by_token, increment_contact
  - buckets : photos-repetiteurs (public), justificatifs-repetiteurs (privé)
  - compte Auth admin
"""

import streamlit as st
import html
import uuid
import urllib.parse
from datetime import datetime, timedelta, timezone
from supabase import create_client, Client

st.set_page_config(page_title="TuteurTD", page_icon="📚", layout="wide")

# ------------------------------------------------------------------
# CONFIGURATION ET SÉCURITÉ DES FICHIERS
# ------------------------------------------------------------------
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 Mo max
ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/jpg"]
ALLOWED_DOC_TYPES = ["image/jpeg", "image/png", "image/jpg", "application/pdf"]

TOUS_NIVEAUX = ["Primaire", "Collège", "Lycée", "Terminale", "Université"]
EXPERIENCE_POIDS = {"Débutant": 1, "1-2 ans": 2, "+3 ans": 3}
BUCKET_PHOTOS = "photos-repetiteurs"
BUCKET_JUSTIFICATIFS = "justificatifs-repetiteurs"

ALLOWED_UPDATE_KEYS = {
    "nom",
    "quartier",
    "zones_couvertes",
    "matieres",
    "niveaux",
    "experience",
    "tarif_horaire",
    "telephone",
    "presentation",
    "photo_url",
    "justificatifs",
    "disponibilites",
}


@st.cache_resource
def get_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])


supabase = get_client()


# ------------------------------------------------------------------
# FONCTIONS UTILITAIRES
# ------------------------------------------------------------------
def initiales(nom):
    parts = (nom or "").split()
    return "".join(p[0] for p in parts[:2]).upper() if parts else "TR"


def esc(texte):
    """Échappe le HTML pour prévenir les attaques XSS stockées."""
    if texte is None:
        return ""
    return html.escape(str(texte), quote=True)


def parser_liste(texte):
    """Convertit 'Maths, Physique,  Maths' en ['Maths', 'Physique']."""
    if not texte:
        return []
    vus, resultat = set(), []
    for item in texte.split(","):
        item = item.strip()
        if item and item not in vus:
            vus.add(item)
            resultat.append(item)
    return resultat


def normaliser_tel(tel: str) -> str:
    """Garde les chiffres et force l'indicatif Tchad 235 si 8 chiffres locaux."""
    digits = "".join(ch for ch in (tel or "") if ch.isdigit())
    if len(digits) == 8:
        return "235" + digits
    if digits.startswith("235") and len(digits) >= 11:
        return digits
    return digits


SIGNATURES_FICHIERS = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"%PDF-": "application/pdf",
}


def type_reel_fichier(fichier):
    """Détecte le type réel du fichier via ses premiers octets (magic bytes),
    indépendamment du Content-Type déclaré par le navigateur (falsifiable)."""
    try:
        entete = fichier.getvalue()[:8]
    except Exception:
        return None
    for signature, mime in SIGNATURES_FICHIERS.items():
        if entete.startswith(signature):
            return mime
    return None


def valider_fichier(fichier, max_size, allowed_types):
    """Valide la taille, le type MIME déclaré ET la signature réelle du fichier."""
    if fichier is None:
        return True, None
    if fichier.size > max_size:
        return (
            False,
            f"Le fichier « {fichier.name} » dépasse {max_size // (1024 * 1024)} Mo.",
        )
    if fichier.type not in allowed_types:
        return False, f"Le format du fichier « {fichier.name} » n'est pas autorisé."
    type_reel = type_reel_fichier(fichier)
    if type_reel is None or type_reel not in allowed_types:
        return (
            False,
            f"Le contenu du fichier « {fichier.name} » ne correspond pas à un "
            "format d'image ou de document valide.",
        )
    return True, None


# ------------------------------------------------------------------
# ACCÈS DONNÉES SUPABASE
# ------------------------------------------------------------------
def charger_repetiteurs_actifs():
    """Lecture publique : la RLS ne renvoie que statut='actif'."""
    try:
        res = (
            supabase.table("repetiteurs")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception:
        st.error("Impossible de charger les profils pour le moment. Réessayez dans un instant.")
        return []


def inserer_repetiteur(payload):
    """
    Insertion via RPC. Le edit_token est généré côté BDD.
    Retourne toujours une string token, ou None.
    """
    try:
        res = supabase.rpc("inserer_nouveau_repetiteur", {"p_payload": payload}).execute()
        data = res.data
        if not data:
            return None
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("edit_token") or data.get("token")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                return first.get("edit_token") or first.get("token")
        return None
    except Exception:
        st.error("L'enregistrement a échoué. Vérifiez vos informations et réessayez.")
        return None


def charger_repetiteurs_admin(client_admin):
    try:
        res = (
            client_admin.table("repetiteurs")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception:
        st.error("Impossible de charger la liste admin.")
        return []


def toggle_statut_admin(client_admin, repet_id, nouveau_statut):
    try:
        client_admin.table("repetiteurs").update({"statut": nouveau_statut}).eq(
            "id", repet_id
        ).execute()
        return True
    except Exception:
        st.error("La mise à jour a échoué (droits admin refusés ?).")
        return False


def obtenir_url_signee_justificatif(client_admin, chemin, expiration_secondes=300):
    """Génère une URL signée temporaire (5 min par défaut) pour un fichier du
    bucket privé justificatifs-repetiteurs. Ne jamais rendre ce bucket public :
    la signature expire, donc un lien partagé par erreur devient inutilisable
    rapidement. Retourne None si la génération échoue (droits, fichier absent)."""
    try:
        res = client_admin.storage.from_(BUCKET_JUSTIFICATIFS).create_signed_url(
            chemin, expiration_secondes
        )
        if isinstance(res, dict):
            return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        return None
    except Exception:
        return None


def incrementer_contact(repet_id):
    try:
        supabase.rpc("increment_contact", {"p_id": repet_id}).execute()
    except Exception:
        pass


def uploader_photo(fichier, edit_token):
    """Upload photo de profil (bucket public), scopée par edit_token —
    même principe que uploader_justificatifs : le chemin doit commencer
    par un edit_token existant pour satisfaire la policy Storage.
    Retourne (url_ou_None, message_erreur_ou_None).
    """
    if fichier is None:
        return None, None

    valide, err = valider_fichier(fichier, MAX_FILE_SIZE, ALLOWED_IMAGE_TYPES)
    if not valide:
        return None, err

    try:
        ext = fichier.name.split(".")[-1].lower()
        if ext not in ("jpg", "jpeg", "png"):
            ext = "jpg"
        token_safe = "".join(ch for ch in str(edit_token) if ch.isalnum() or ch in "-_")
        nom_fichier = f"{token_safe}/{uuid.uuid4()}.{ext}"
        supabase.storage.from_(BUCKET_PHOTOS).upload(
            nom_fichier,
            fichier.getvalue(),
            {"content-type": fichier.type or "image/jpeg"},
        )
        return supabase.storage.from_(BUCKET_PHOTOS).get_public_url(nom_fichier), None
    except Exception as exc:
        return None, f"La photo n'a pas pu être envoyée ({exc}) — le profil sera créé/mis à jour sans photo."


def uploader_justificatifs(fichiers, edit_token):
    """Upload justificatifs (bucket privé). Noms 100 % générés.
    Retourne (chemins, messages_erreur) — même principe que uploader_photo.
    """
    chemins = []
    messages = []
    token_safe = "".join(ch for ch in str(edit_token) if ch.isalnum() or ch in "-_")
    for fichier in fichiers or []:
        valide, err = valider_fichier(fichier, MAX_FILE_SIZE, ALLOWED_DOC_TYPES)
        if not valide:
            messages.append(err)
            continue
        try:
            ext = fichier.name.split(".")[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "pdf"):
                ext = "bin"
            chemin = f"{token_safe}/{uuid.uuid4()}.{ext}"
            supabase.storage.from_(BUCKET_JUSTIFICATIFS).upload(
                chemin,
                fichier.getvalue(),
                {"content-type": fichier.type or "application/octet-stream"},
            )
            chemins.append(chemin)
        except Exception as exc:
            messages.append(f"Le fichier « {fichier.name} » n'a pas pu être envoyé ({exc}).")
    return chemins, messages
    return chemins


def get_repetiteur_par_token(token):
    try:
        res = supabase.rpc("get_repetiteur_by_token", {"p_token": token}).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def maj_repetiteur_par_token(token, updates):
    """Update via RPC après filtrage strict des champs autorisés."""
    updates_filtres = {k: v for k, v in updates.items() if k in ALLOWED_UPDATE_KEYS}
    try:
        supabase.rpc(
            "update_repetiteur_by_token",
            {"p_token": token, "p_updates": updates_filtres},
        ).execute()
        return True
    except Exception:
        st.error("La mise à jour a échoué. Vérifiez votre code personnel.")
        return False


def lien_edition(token):
    base = st.secrets.get("APP_URL", "").rstrip("/")
    return f"{base}/?edit={token}" if base else None


def charger_avis_stats():
    try:
        res = supabase.table("avis").select("repetiteur_id, note").execute()
        groupes = {}
        for a in res.data or []:
            groupes.setdefault(a["repetiteur_id"], []).append(a["note"])
        return {
            rid: (sum(notes) / len(notes), len(notes)) for rid, notes in groupes.items()
        }
    except Exception:
        return {}


def ajouter_avis(repet_id, note, commentaire):
    try:
        supabase.table("avis").insert(
            {
                "repetiteur_id": repet_id,
                "note": note,
                "commentaire": commentaire.strip() if commentaire else None,
            },
            returning="minimal",
        ).execute()
        return True
    except Exception:
        st.error("L'avis n'a pas pu être enregistré.")
        return False


def score_pertinence(r, avis_stats):
    exp = EXPERIENCE_POIDS.get(r.get("experience"), 1)
    contacts = r.get("nb_contacts", 0) or 0
    moyenne, nb_avis = avis_stats.get(r["id"], (0, 0))
    return exp * 3 + contacts * 1 + moyenne * nb_avis * 2


def est_recent(created_at_str, jours=7):
    try:
        created = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - created < timedelta(days=jours)
    except Exception:
        return False


# ------------------------------------------------------------------
# SESSION ADMIN
# ------------------------------------------------------------------
def get_admin_client():
    session = st.session_state.get("admin_session")
    if not session:
        return None
    client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
    try:
        client.auth.set_session(session["access_token"], session["refresh_token"])
        return client
    except Exception:
        st.session_state.pop("admin_session", None)
        return None


def admin_login(email, mot_de_passe):
    try:
        client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"])
        auth_res = client.auth.sign_in_with_password(
            {"email": email, "password": mot_de_passe}
        )
        st.session_state.admin_session = {
            "access_token": auth_res.session.access_token,
            "refresh_token": auth_res.session.refresh_token,
        }
        return True
    except Exception:
        st.error("Identifiants incorrects.")
        return False


# ------------------------------------------------------------------
# STYLE
# ------------------------------------------------------------------
st.markdown(
    """
<style>
:root {
    --bg: #0b1220;
    --surface: #121a2b;
    --border: rgba(94, 234, 212, 0.18);
    --teal: #2dd4bf;
    --teal-dim: rgba(45, 212, 191, 0.12);
    --text: #e8eef7;
    --muted: #8b9bb4;
    --warning: #fbbf24;
    --radius: 16px;
    --shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
}
.stApp {
    background:
        radial-gradient(ellipse at 20% 0%, rgba(45, 212, 191, 0.12), transparent 50%),
        radial-gradient(ellipse at 80% 100%, rgba(99, 102, 241, 0.1), transparent 45%),
        var(--bg);
    color: var(--text);
}
[data-testid="stHeader"] { background: transparent; }
h1, h2, h3, p, span, label, div { color: var(--text); }
.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.logo {
    width: 42px; height: 42px; border-radius: 12px;
    background: linear-gradient(135deg, var(--teal), #6366f1);
    display: grid; place-items: center; font-weight: 700; font-size: 1.1rem; color: #06201c;
}
.brand h1 { font-size: 1.35rem; letter-spacing: -0.02em; margin: 0; }
.brand p { color: var(--muted); font-size: 0.82rem; margin: 0; }
.hero {
    background: linear-gradient(135deg, rgba(45, 212, 191, 0.1), rgba(99, 102, 241, 0.08));
    border: 1px solid var(--border); border-radius: var(--radius);
    padding: 22px 20px; margin-bottom: 18px;
}
.hero h2 { font-size: 1.45rem; margin-bottom: 6px; }
.hero p { color: var(--muted); font-size: 0.95rem; margin: 0; }
.stat {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 12px; text-align: center;
}
.stat strong { display: block; font-size: 1.25rem; color: var(--teal); }
.stat span { color: var(--muted); font-size: 0.78rem; }
.card {
    background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 16px; box-shadow: var(--shadow); margin-bottom: 14px;
}
.card-head { display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }
.avatar {
    width: 48px; height: 48px; border-radius: 50%;
    background: linear-gradient(145deg, #2dd4bf, #6366f1);
    display: grid; place-items: center; font-weight: 700; color: #06201c; flex-shrink: 0;
}
.avatar-img {
    width: 48px; height: 48px; border-radius: 50%; object-fit: cover; flex-shrink: 0;
    border: 1px solid var(--border);
}
.card-head h3 { font-size: 1.02rem; margin: 0; }
.card-head .meta { color: var(--muted); font-size: 0.8rem; }
.note { font-size: 0.78rem; color: var(--warning); margin-bottom: 6px; }
.note.muted { color: var(--muted); }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.badge {
    background: var(--teal-dim); color: var(--teal); border: 1px solid rgba(45, 212, 191, 0.25);
    font-size: 0.72rem; font-weight: 600; padding: 3px 8px; border-radius: 999px;
}
.badge.muted {
    background: rgba(139, 155, 180, 0.12); color: var(--muted);
    border-color: rgba(139, 155, 180, 0.2);
}
.badge.nouveau {
    background: rgba(251, 191, 36, 0.15); color: var(--warning);
    border-color: rgba(251, 191, 36, 0.3);
}
.card p.desc { color: var(--muted); font-size: 0.86rem; }
.price { font-weight: 700; color: var(--text); font-size: 0.95rem; }
.price span { color: var(--muted); font-weight: 500; font-size: 0.78rem; }
.empty {
    text-align: center; padding: 36px 16px; color: var(--muted);
    border: 1px dashed var(--border); border-radius: var(--radius);
}
.status {
    font-size: 0.78rem; font-weight: 600; padding: 3px 10px; border-radius: 999px;
}
.status.actif { background: rgba(45, 212, 191, 0.15); color: var(--teal); }
.status.attente { background: rgba(251, 191, 36, 0.15); color: var(--warning); }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="topbar">
  <div class="logo">T</div>
  <div class="brand">
    <h1>TuteurTD</h1>
    <p>Répétiteurs de maison à N'Djamena</p>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

tab_parent, tab_tuteur, tab_edition, tab_admin = st.tabs(
    ["👨‍👩‍👧 Parent", "👩‍🏫 Répétiteur", "✏️ Modifier mon profil", "🛠️ Admin"]
)

# ------------------------------------------------------------------
# ONGLET PARENT
# ------------------------------------------------------------------
with tab_parent:
    repetiteurs = charger_repetiteurs_actifs()

    def toutes_matieres():
        return sorted({m for r in repetiteurs for m in r.get("matieres", []) or []})

    def tous_quartiers():
        return sorted(
            {z for r in repetiteurs for z in r.get("zones_couvertes", []) or []}
        )

    st.markdown(
        """
    <div class="hero">
      <h2>Trouvez le bon répétiteur</h2>
      <p>Filtrez par matière, niveau, quartier et budget. Contactez directement sur WhatsApp.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    s1, s2, s3 = st.columns(3)
    with s1:
        st.markdown(
            f'<div class="stat"><strong>{len(repetiteurs)}</strong><span>profils visibles</span></div>',
            unsafe_allow_html=True,
        )
    with s2:
        st.markdown(
            f'<div class="stat"><strong>{len(tous_quartiers())}</strong><span>quartiers couverts</span></div>',
            unsafe_allow_html=True,
        )
    with s3:
        st.markdown(
            f'<div class="stat"><strong>{len(toutes_matieres())}</strong><span>matières</span></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    search_query = st.text_input(
        "🔍 Rechercher un nom ou un mot-clé",
        placeholder="Ex: Mathématiques, Amina, expérience...",
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        matiere_filtre = st.multiselect("Matière (une ou plusieurs)", toutes_matieres())
    with c2:
        niveau_filtre = st.selectbox("Niveau", ["Tous"] + TOUS_NIVEAUX)
    with c3:
        quartier_filtre = st.multiselect(
            "Quartier / zone (un ou plusieurs)", tous_quartiers()
        )
    with c4:
        budget_max = st.number_input(
            "Budget max (FCFA/h)", min_value=0, value=5000, step=250
        )

    tri = st.radio(
        "Trier par",
        ["Pertinence", "Plus récents", "Prix croissant", "Prix décroissant"],
        horizontal=True,
    )

    avis_stats = charger_avis_stats()

    def correspond(r):
        if matiere_filtre and not any(
            m in (r.get("matieres") or []) for m in matiere_filtre
        ):
            return False
        if niveau_filtre != "Tous" and niveau_filtre not in (r.get("niveaux") or []):
            return False
        if quartier_filtre and not any(
            z in (r.get("zones_couvertes") or []) for z in quartier_filtre
        ):
            return False
        if (r.get("tarif_horaire") or 0) > budget_max:
            return False
        if search_query:
            q = search_query.strip().lower()
            texte = " ".join(
                [
                    r.get("nom") or "",
                    r.get("presentation") or "",
                    " ".join(r.get("matieres") or []),
                    r.get("quartier") or "",
                ]
            ).lower()
            if q not in texte:
                return False
        return True

    resultats = [r for r in repetiteurs if correspond(r)]

    if tri == "Pertinence":
        resultats.sort(key=lambda r: score_pertinence(r, avis_stats), reverse=True)
    elif tri == "Prix croissant":
        resultats.sort(key=lambda r: r.get("tarif_horaire") or 0)
    elif tri == "Prix décroissant":
        resultats.sort(key=lambda r: r.get("tarif_horaire") or 0, reverse=True)

    signature_filtres = (
        tuple(sorted(matiere_filtre)),
        niveau_filtre,
        tuple(sorted(quartier_filtre)),
        budget_max,
        tri,
        search_query,
    )
    if st.session_state.get("_signature_filtres") != signature_filtres:
        st.session_state._signature_filtres = signature_filtres
        st.session_state.nb_affiches = 9
    if "nb_affiches" not in st.session_state:
        st.session_state.nb_affiches = 9

    st.write("")
    if not resultats:
        st.markdown(
            '<div class="empty">Aucun profil ne correspond à vos filtres.</div>',
            unsafe_allow_html=True,
        )
    else:
        resultats_page = resultats[: st.session_state.nb_affiches]
        cols = st.columns(3)
        for i, r in enumerate(resultats_page):
            with cols[i % 3]:
                badges = "".join(
                    f'<span class="badge">{esc(m)}</span>'
                    for m in (r.get("matieres") or [])
                )
                badges += "".join(
                    f'<span class="badge muted">{esc(n)}</span>'
                    for n in (r.get("niveaux") or [])
                )
                nouveau_html = (
                    '<span class="badge nouveau">🆕 Nouveau</span>'
                    if est_recent(r.get("created_at") or "")
                    else ""
                )

                nom_affiche = esc(r.get("nom") or "")
                if r.get("photo_url"):
                    avatar_html = (
                        f'<img src="{esc(r["photo_url"])}" class="avatar-img" '
                        f'alt="{nom_affiche}">'
                    )
                else:
                    avatar_html = (
                        f'<div class="avatar">{esc(initiales(r.get("nom") or ""))}</div>'
                    )

                moyenne, nb_avis = avis_stats.get(r["id"], (0, 0))
                if nb_avis > 0:
                    note_html = (
                        f'<div class="note">⭐ {moyenne:.1f}/5 · {nb_avis} avis</div>'
                    )
                else:
                    note_html = '<div class="note muted">Pas encore d\'avis</div>'

                tarif = r.get("tarif_horaire") or 0
                st.markdown(
                    f"""
                <div class="card">
                  <div class="card-head">
                    {avatar_html}
                    <div>
                      <h3>{nom_affiche}</h3>
                      <div class="meta">{esc(r.get("quartier"))} · {esc(r.get("experience"))}</div>
                    </div>
                  </div>
                  {note_html}
                  <div class="badges">{nouveau_html}{badges}</div>
                  <p class="desc">{esc(r.get("presentation"))}</p>
                  <div class="price">{tarif:,} <span>FCFA/h</span></div>
                </div>
                """.replace(",", " "),
                    unsafe_allow_html=True,
                )

                if st.button(
                    "💬 Contacter sur WhatsApp", key=f"btn_contact_{r['id']}"
                ):
                    incrementer_contact(r["id"])
                    msg = urllib.parse.quote(
                        f"Bonjour {r.get('nom') or ''}, je vous contacte via TuteurTD "
                        f"pour des cours particuliers."
                    )
                    tel_clean = normaliser_tel(r.get("telephone") or "")
                    url_wa = f"https://wa.me/{tel_clean}?text={msg}"
                    st.markdown(
                        f'<a href="{url_wa}" target="_blank" rel="noopener">'
                        f"Ouvrir la discussion WhatsApp</a>",
                        unsafe_allow_html=True,
                    )
                    st.toast("Redirection vers WhatsApp...")

                avis_donnes = st.session_state.setdefault("avis_donnes", set())
                if r["id"] not in avis_donnes:
                    with st.expander("⭐ Laisser un avis"):
                        with st.form(f"form_avis_{r['id']}", clear_on_submit=True):
                            note_choisie = st.slider(
                                "Note", 1, 5, 5, key=f"note_{r['id']}"
                            )
                            commentaire = st.text_area(
                                "Commentaire (optionnel)", key=f"comm_{r['id']}"
                            )
                            if st.form_submit_button("Envoyer mon avis"):
                                if ajouter_avis(r["id"], note_choisie, commentaire):
                                    avis_donnes.add(r["id"])
                                    st.toast("Merci pour votre avis 🙏")
                                    st.rerun()
                else:
                    st.caption("✅ Avis envoyé — merci !")

        if len(resultats) > len(resultats_page):
            st.write("")
            _, col_plus, _ = st.columns([2, 1, 2])
            with col_plus:
                restants = len(resultats) - len(resultats_page)
                if st.button(f"Charger plus de profils ({restants} restants)"):
                    st.session_state.nb_affiches += 9
                    st.rerun()

# ------------------------------------------------------------------
# ONGLET RÉPÉTITEUR
# ------------------------------------------------------------------
with tab_tuteur:
    st.markdown(
        """
    <div class="hero">
      <h2>Devenir répétiteur</h2>
      <p>Créez votre profil en quelques minutes. Les parents pourront vous trouver et vous contacter.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    if st.session_state.get("profil_ajoute"):
        token_genere = st.session_state.get("dernier_edit_token", "")
        lien = lien_edition(token_genere)
        st.success(
            "✅ Profil enregistré ! Il sera visible après validation par un administrateur."
        )
        for msg in st.session_state.get("dernier_avertissements_upload", []):
            st.warning(msg)
        st.warning(
            "⚠️ **Conservez ce code personnel** — c'est le seul moyen de modifier "
            "votre profil plus tard (aucun compte n'est créé)."
        )
        st.code(lien or token_genere, language=None)
        if not lien:
            st.caption(
                "Collez ce code dans l'onglet « ✏️ Modifier mon profil » pour l'utiliser."
            )
        st.session_state.profil_ajoute = False

    with st.form("form_tuteur", clear_on_submit=True):
        fc1, fc2 = st.columns(2)
        with fc1:
            nom = st.text_input("Nom complet *", placeholder="Ex: Amina Mahamat")
            quartier = st.text_input(
                "Quartier principal *", placeholder="Ex: Chagoua"
            )
            autres_quartiers_input = st.text_input(
                "Autres quartiers couverts (optionnel, séparés par virgule)",
                placeholder="Ex: Diguel, Walia",
            )
            matieres_input = st.text_input(
                "Matières enseignées * (séparées par virgule)",
                placeholder="Ex: Mathématiques, Physique",
            )
            niveaux_input = st.multiselect(
                "Niveaux visés *", TOUS_NIVEAUX, default=[]
            )
        with fc2:
            telephone = st.text_input(
                "Téléphone WhatsApp *", placeholder="Ex: 66001234 ou 23566001234"
            )
            tarif = st.number_input(
                "Tarif indicatif (FCFA/heure) *",
                min_value=500,
                step=250,
                value=2000,
            )
            experience = st.selectbox(
                "Expérience", ["Débutant", "1-2 ans", "+3 ans"]
            )
            dispo = st.text_input(
                "Disponibilités", placeholder="Ex: Soirs + week-end"
            )
        bio = st.text_area(
            "Présentation courte",
            placeholder="Parlez de votre parcours, méthode, résultats…",
        )
        photo = st.file_uploader(
            "Photo de profil (optionnel, max 5 Mo)", type=["jpg", "jpeg", "png"]
        )
        justificatifs_files = st.file_uploader(
            "Justificatifs — diplôme, CNI (optionnel, max 5 Mo / fichier)",
            type=["jpg", "jpeg", "png", "pdf"],
            accept_multiple_files=True,
        )

        submitted = st.form_submit_button("Publier mon profil")
        if submitted:
            matieres_liste = parser_liste(matieres_input)
            if (
                not nom
                or not telephone
                or not quartier
                or not matieres_liste
                or not niveaux_input
            ):
                st.error("Merci de remplir tous les champs obligatoires (*).")
            else:
                avertissements_upload = []
                payload = {
                    "nom": nom.strip(),
                    "quartier": quartier.strip(),
                    "zones_couvertes": [quartier.strip()]
                    + parser_liste(autres_quartiers_input),
                    "matieres": matieres_liste,
                    "niveaux": list(niveaux_input),
                    "photo_url": None,
                    "experience": experience,
                    "tarif_horaire": int(tarif),
                    "telephone": normaliser_tel(telephone),
                    "presentation": bio.strip() or "Nouveau profil répétiteur.",
                    "disponibilites": dispo.strip() or None,
                    "statut": "attente",
                }

                token_genere = inserer_repetiteur(payload)
                if token_genere:
                    updates_post_insert = {}
                    if photo is not None:
                        photo_url, err_photo = uploader_photo(photo, token_genere)
                        if err_photo:
                            avertissements_upload.append(err_photo)
                        if photo_url:
                            updates_post_insert["photo_url"] = photo_url
                    if justificatifs_files:
                        chemins, err_justificatifs = uploader_justificatifs(
                            justificatifs_files, token_genere
                        )
                        avertissements_upload.extend(err_justificatifs)
                        if chemins:
                            updates_post_insert["justificatifs"] = chemins
                    if updates_post_insert:
                        maj_repetiteur_par_token(token_genere, updates_post_insert)
                    st.session_state.dernier_avertissements_upload = avertissements_upload
                    st.session_state.profil_ajoute = True
                    st.session_state.dernier_edit_token = token_genere
                    st.rerun()

    st.caption(
        "* Champs obligatoires. Un administrateur doit valider votre profil avant qu'il soit visible."
    )

# ------------------------------------------------------------------
# ONGLET ÉDITION
# ------------------------------------------------------------------
with tab_edition:
    st.markdown(
        """
    <div class="hero">
      <h2>Modifier mon profil</h2>
      <p>Collez votre code personnel reçu à l'inscription pour mettre à jour vos informations.</p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    token_url = st.query_params.get("edit", "")
    token_saisi = st.text_input(
        "Code personnel *",
        value=token_url,
        placeholder="Ex: 8f3c1a2b-4d5e-...",
    )

    if token_saisi:
        profil = get_repetiteur_par_token(token_saisi.strip())
        if not profil:
            st.error("Code invalide. Vérifiez qu'il est correctement copié.")
        else:
            st.success(f"Profil trouvé : **{esc(profil.get('nom'))}**")
            for msg in st.session_state.pop("dernier_avertissements_edition", []):
                st.warning(msg)
            with st.form("form_edition"):
                ec1, ec2 = st.columns(2)
                with ec1:
                    e_nom = st.text_input(
                        "Nom complet *", value=profil.get("nom") or ""
                    )
                    e_quartier = st.text_input(
                        "Quartier principal *", value=profil.get("quartier") or ""
                    )
                    e_autres_quartiers = st.text_input(
                        "Autres quartiers couverts (séparés par virgule)",
                        value=", ".join(
                            z
                            for z in (profil.get("zones_couvertes") or [])
                            if z != profil.get("quartier")
                        ),
                    )
                    e_matieres = st.text_input(
                        "Matières * (séparées par virgule)",
                        value=", ".join(profil.get("matieres") or []),
                    )
                    e_niveaux = st.multiselect(
                        "Niveaux visés *",
                        TOUS_NIVEAUX,
                        default=[
                            n
                            for n in (profil.get("niveaux") or [])
                            if n in TOUS_NIVEAUX
                        ],
                    )
                with ec2:
                    e_telephone = st.text_input(
                        "Téléphone WhatsApp *",
                        value=profil.get("telephone") or "",
                    )
                    e_tarif = st.number_input(
                        "Tarif indicatif (FCFA/heure) *",
                        min_value=500,
                        step=250,
                        value=int(profil.get("tarif_horaire") or 2000),
                    )
                    experiences = ["Débutant", "1-2 ans", "+3 ans"]
                    exp_val = profil.get("experience") or "Débutant"
                    e_experience = st.selectbox(
                        "Expérience",
                        experiences,
                        index=experiences.index(exp_val)
                        if exp_val in experiences
                        else 0,
                    )
                    e_dispo = st.text_input(
                        "Disponibilités",
                        value=profil.get("disponibilites") or "",
                    )
                e_bio = st.text_area(
                    "Présentation courte",
                    value=profil.get("presentation") or "",
                )
                e_photo = st.file_uploader(
                    "Nouvelle photo (remplace l'actuelle, max 5 Mo)",
                    type=["jpg", "jpeg", "png"],
                )
                e_justificatifs = st.file_uploader(
                    "Ajouter des justificatifs (diplôme, CNI, max 5 Mo / fichier)",
                    type=["jpg", "jpeg", "png", "pdf"],
                    accept_multiple_files=True,
                )
                st.caption(
                    f"{len(profil.get('justificatifs') or [])} justificatif(s) déjà envoyé(s)."
                )

                if st.form_submit_button("Enregistrer les modifications"):
                    matieres_liste = parser_liste(e_matieres)
                    if (
                        not e_nom
                        or not e_telephone
                        or not e_quartier
                        or not matieres_liste
                        or not e_niveaux
                    ):
                        st.error("Merci de remplir tous les champs obligatoires (*).")
                    else:
                        updates = {
                            "nom": e_nom.strip(),
                            "quartier": e_quartier.strip(),
                            "zones_couvertes": [e_quartier.strip()]
                            + parser_liste(e_autres_quartiers),
                            "matieres": matieres_liste,
                            "niveaux": list(e_niveaux),
                            "experience": e_experience,
                            "tarif_horaire": int(e_tarif),
                            "telephone": normaliser_tel(e_telephone),
                            "presentation": e_bio.strip(),
                            "disponibilites": e_dispo.strip() or None,
                        }
                        avertissements_upload = []
                        if e_photo is not None:
                            nouvelle_photo, err_photo = uploader_photo(e_photo, token_saisi.strip())
                            if err_photo:
                                avertissements_upload.append(err_photo)
                            if nouvelle_photo:
                                updates["photo_url"] = nouvelle_photo
                        if e_justificatifs:
                            nouveaux, err_justificatifs = uploader_justificatifs(
                                e_justificatifs, token_saisi.strip()
                            )
                            avertissements_upload.extend(err_justificatifs)
                            updates["justificatifs"] = (
                                profil.get("justificatifs") or []
                            ) + nouveaux

                        if maj_repetiteur_par_token(token_saisi.strip(), updates):
                            st.session_state.dernier_avertissements_edition = avertissements_upload
                            st.success("✅ Profil mis à jour.")
                            st.rerun()

# ------------------------------------------------------------------
# ONGLET ADMIN
# ------------------------------------------------------------------
with tab_admin:
    admin_client = get_admin_client()

    if admin_client is None:
        st.markdown(
            """
        <div class="hero">
          <h2>Connexion admin</h2>
          <p>Connectez-vous avec votre compte administrateur Supabase.</p>
        </div>
        """,
            unsafe_allow_html=True,
        )
        with st.form("form_admin_login"):
            email = st.text_input("Email admin")
            mot_de_passe = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter"):
                if admin_login(email, mot_de_passe):
                    st.rerun()
    else:
        col_titre, col_logout = st.columns([4, 1])
        with col_titre:
            st.markdown(
                """
            <div class="hero">
              <h2>Validation des profils</h2>
              <p>Activer, suspendre, contrôler la qualité des profils.</p>
            </div>
            """,
                unsafe_allow_html=True,
            )
        with col_logout:
            if st.button("Déconnexion"):
                st.session_state.pop("admin_session", None)
                st.rerun()

        repetiteurs_admin = charger_repetiteurs_admin(admin_client)

        hdr = st.columns([2, 1.8, 1.8, 1.2, 1, 1.2, 1.5])
        for col, label in zip(
            hdr,
            ["Nom", "Matière", "Quartier", "Tarif", "Contacts", "Statut", "Action"],
        ):
            col.markdown(f"**{label}**")
        st.markdown(
            "<hr style='border-color: rgba(94,234,212,0.18); margin: 4px 0 8px;'>",
            unsafe_allow_html=True,
        )

        for r in repetiteurs_admin:
            row = st.columns([2, 1.8, 1.8, 1.2, 1, 1.2, 1.5])
            row[0].write(esc(r.get("nom")))
            row[1].write(", ".join(r.get("matieres") or []))
            row[2].write(esc(r.get("quartier")))
            row[3].write(f"{r.get('tarif_horaire') or 0:,} F".replace(",", " "))
            row[4].write(str(r.get("nb_contacts") or 0))
            statut = r.get("statut") or "attente"
            statut_class = "actif" if statut == "actif" else "attente"
            statut_label = "Actif" if statut == "actif" else "En attente"
            row[5].markdown(
                f'<span class="status {statut_class}">{statut_label}</span>',
                unsafe_allow_html=True,
            )
            bouton_label = "Suspendre" if statut == "actif" else "Activer"
            if row[6].button(bouton_label, key=f"toggle_{r['id']}"):
                nouveau = "attente" if statut == "actif" else "actif"
                if toggle_statut_admin(admin_client, r["id"], nouveau):
                    st.rerun()

            justificatifs_r = r.get("justificatifs") or []
            if justificatifs_r:
                with st.expander(f"📎 {len(justificatifs_r)} justificatif(s) — {esc(r.get('nom'))}"):
                    for chemin in justificatifs_r:
                        url_signee = obtenir_url_signee_justificatif(admin_client, chemin)
                        if not url_signee:
                            st.caption(f"⚠️ Lien indisponible pour ce fichier ({chemin}).")
                        elif chemin.lower().endswith((".jpg", ".jpeg", ".png")):
                            st.image(url_signee, width=240)
                        else:
                            st.markdown(f"[📄 Ouvrir le document (lien valable 5 min)]({url_signee})")
            else:
                st.caption(f"⚠️ Aucun justificatif fourni par {esc(r.get('nom'))}.")

st.markdown(
    "<footer style='margin-top:28px;text-align:center;color:#8b9bb4;font-size:0.8rem;'>"
    "TuteurTD · Projet répétiteurs de maison · N'Djamena</footer>",
    unsafe_allow_html=True,
)
